"""Restoring the database from a backup without leaving the web program (the administrator's page «Копии»).

The chosen copy is unpacked and checked first (readable, not newer than this program); then the program goes into the maintenance mode (other
requests get a "wait" page), a safety copy of the current database is made, the copy is poured into the live database by the backup
interface of SQLite, the migrations are applied, the sessions of everybody are ended and the restore is written to the audit log.
The tray command «Восстановить из копии…» stays for the case when the database is too damaged for the program to start."""
from __future__ import annotations

import gzip
import logging
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from app import backups, db, health

log = logging.getLogger("trs398.restore")
NAME_RE = re.compile(r"^(keep/)?trs398[A-Za-z0-9_\-]*\.db\.gz$")                 # the folder of the backups or its folder keep/
DRAIN_SECONDS = 15                                     # how long the requests that are already running may take to finish
VALID_FROM = "sessions_valid_from.txt"                 # the sign-ins made before this moment are over (a restore may change the users)


class RestoreError(Exception):
    pass


class State:
    on = False                                         # the maintenance mode: the middleware answers every request with the "wait" page
    active = 0                                         # the requests that are being served now (counted by the middleware)
    lock = threading.Lock()


state = State()


# ------------------------------------------------------------------------------------------------ sessions
def valid_from() -> float:
    try:
        return float((db.data_dir() / VALID_FROM).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def mark(when: float | None = None) -> None:
    """Every sign-in made before now is over: the users of the restored database may be other people."""
    try:
        (db.data_dir() / VALID_FROM).write_text(str(time.time() if when is None else when), encoding="utf-8")
    except OSError:
        log.exception("could not write %s", VALID_FROM)


# ------------------------------------------------------------------------------------------------ the copy
def backup_path(name: str) -> Path:
    """The file of a backup of the program by its name (only files of the backups folder, nothing else)."""
    if not NAME_RE.match(name or ""):
        raise RestoreError("Это не файл копии программы")
    path = backups.backup_dir() / name
    if not path.is_file():
        raise RestoreError("Файл копии не найден")
    return path


def unpack(src: Path, dest: Path) -> None:
    with open(src, "rb") as f:
        magic = f.read(16)
    if magic.startswith(b"SQLite format 3"):
        shutil.copyfile(src, dest)
        return
    with gzip.open(src, "rb") as f_in, open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def _counts(path: Path) -> dict:
    """What a database file holds (read-only): the numbers for the comparison and the migrations it has seen."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        def one(sql):
            try:
                return conn.execute(sql).fetchone()[0]
            except sqlite3.Error:
                return None
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()} if one("SELECT count(*) FROM sqlite_master WHERE name = 'schema_migrations'") else set()
        return {"measurements": one("SELECT count(*) FROM measurement_sessions"), "users": one("SELECT count(*) FROM users"),
                "last_measured": one("SELECT max(measured_on) FROM measurement_sessions"), "last_audit": one("SELECT max(at) FROM audit_log"),
                "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0], "migrations": done}
    finally:
        conn.close()


def preview(name: str) -> dict:
    """What the restore of this copy would do: its content against the current database and whether it can be done at all."""
    src = backup_path(name)
    with tempfile.TemporaryDirectory(dir=db.data_dir()) as tmp:
        new = Path(tmp) / "copy.db"
        try:
            unpack(src, new)
            theirs = _counts(new)
        except (OSError, EOFError, gzip.BadGzipFile, sqlite3.Error) as e:
            return {"name": name, "ok": False, "problem": f"Копия не читается: {e}"}
    ours = _counts(db.db_path())
    known = {p.name for p in db.MIGRATIONS.glob("*.sql")}
    newer = sorted(theirs["migrations"] - known)
    problem = ""
    if theirs["integrity"] != "ok":
        problem = f"Копия повреждена: {theirs['integrity']}"
    elif newer:
        problem = "Копия сделана более новой версией программы: обновите программу, затем восстанавливайте"
    elif not theirs["users"]:
        problem = "В копии нет ни одного пользователя"
    return {"name": name, "ok": not problem, "problem": problem, "theirs": theirs, "ours": ours,
            "when": datetime.fromtimestamp(src.stat().st_mtime), "size_kb": max(1, src.stat().st_size // 1024),
            "upgrade": sorted(known - theirs["migrations"])}


def _wait_for_idle() -> None:
    """The restore itself is one of the running requests."""
    end = time.monotonic() + DRAIN_SECONDS
    while state.active > 1:
        if time.monotonic() > end:
            raise RestoreError("Программа занята другими запросами. Повторите через минуту")
        time.sleep(0.2)


def perform(actor_login: str, name: str, reason: str) -> dict:
    """Restore the database from the copy. Raises RestoreError with the text for the administrator; the database is changed only after the
    copy has been checked and the safety copy made."""
    if len((reason or "").strip()) < 5:
        raise RestoreError("Укажите причину восстановления (не короче 5 символов)")
    if not state.lock.acquire(blocking=False):
        raise RestoreError("Восстановление уже идёт")
    try:
        info = preview(name)
        if not info["ok"]:
            raise RestoreError(info["problem"])
        src = backup_path(name)
        target = db.db_path()
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            new = Path(tmp) / "copy.db"
            unpack(src, new)
            keep = backups.backup_dir() / "keep"
            keep.mkdir(parents=True, exist_ok=True)
            state.on = True                                # from here on other requests wait
            try:
                _wait_for_idle()
                try:
                    safety = backups.make(folder=keep, name_prefix="trs398_before_restore")
                except Exception as e:                    # noqa: BLE001
                    raise RestoreError(f"Не удалось сохранить текущую базу, ничего не изменено: {e}")
                source = sqlite3.connect(new)
                dest = sqlite3.connect(target, timeout=30)
                try:
                    source.backup(dest)
                    dest.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    dest.commit()
                finally:
                    dest.close()
                    source.close()
                conn = db.connect()
                try:
                    applied = db.migrate(conn)
                    conn.commit()
                finally:
                    conn.close()
                mark()
                health.check()
                db.system_event("restore", "system", None, {"file": name, "by": actor_login, "reason": reason.strip(), "via": "web",
                                                          "safety_copy": safety.name, "migrations": applied})
                log.warning("the database was restored from %s by %s (safety copy %s)", name, actor_login, safety.name)
            finally:
                state.on = False
        return {"name": name, "safety_copy": safety.name, "measurements": info["theirs"]["measurements"], "upgraded": applied}
    finally:
        state.lock.release()
