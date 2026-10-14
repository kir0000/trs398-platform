"""Backups of the database: a consistent copy of the SQLite file (the backup API, safe while the program works), compressed,
made every day inside the program and kept for BACKUP_KEEP_DAYS days. The restore tool (tools/restore.py) brings a copy back."""
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from app import db, health, settings

STALE_AFTER = timedelta(hours=36)
PATTERN = "trs398_*.db.gz"
_lock = threading.Lock()
log = logging.getLogger("trs398.backups")


def backup_dir() -> Path:
    p = Path(os.environ["BACKUP_DIR"]) if os.environ.get("BACKUP_DIR") else db.data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def copy_dir() -> Path | None:
    """The folder for the second copy of every backup (a network folder, a USB stick, a synchronised disk), if one is set."""
    raw = os.environ.get("BACKUP_COPY_DIR") or settings.load().get("backup_copy_dir") or ""
    return Path(raw) if raw.strip() else None


def _status_file() -> Path:
    return db.data_dir() / "backup_external.json"


def _write_status(**fields) -> None:
    try:
        _status_file().write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def copy_out(src: Path) -> bool | None:
    """Copy a backup file to the second place and remove the old ones there. None: no second place is set."""
    target_dir = copy_dir()
    if target_dir is None:
        return None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target_dir / src.name)
        cutoff = time.time() - keep_days() * 86400
        for old in target_dir.glob(PATTERN):
            if old.name != src.name and old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
        _write_status(when=datetime.now().isoformat(timespec="seconds"), name=src.name, path=str(target_dir), error=None)
        log.info("second copy made: %s -> %s", src.name, target_dir)
        return True
    except Exception as e:                                       # noqa: BLE001  (unplugged disk, no rights, no network)
        _write_status(when=_read_status().get("when"), name=_read_status().get("name"), path=str(target_dir), error=str(e)[:200],
                      failed_at=datetime.now().isoformat(timespec="seconds"))
        log.exception("the second copy failed (%s)", target_dir)
        db.system_event("backup_copy_failed", "backups", None, {"folder": str(target_dir), "error": str(e)[:200]})
        return False


def _read_status() -> dict:
    try:
        return json.loads(_status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def external_status(now: datetime | None = None) -> dict:
    """{'configured', 'path', 'ok', 'when', 'name', 'error', 'stale', 'message'}: the state of the second copy."""
    now = now or datetime.now()
    d = copy_dir()
    if d is None:
        return {"configured": False, "ok": False, "stale": False,
                "message": "Вторая копия не настроена: все копии лежат на этом же компьютере."}
    st = _read_status()
    when = datetime.fromisoformat(st["when"]) if st.get("when") else None
    stale = when is None or now - when > STALE_AFTER
    if st.get("error"):
        msg = f"Не удалось сделать вторую копию: {st['error']}"
    elif when is None:
        msg = "Вторая копия ещё не делалась."
    elif stale:
        msg = "Последняя вторая копия старше 36 часов: проверьте, подключена ли папка."
    else:
        msg = "Вторая копия свежая."
    return {"configured": True, "path": str(d), "ok": not stale and not st.get("error"), "when": when, "name": st.get("name"),
            "error": st.get("error"), "stale": stale or bool(st.get("error")), "message": msg}


def set_copy_dir(raw: str) -> tuple[bool, str]:
    """Save the folder of the second copy after checking that it can be written; the newest backup is copied there at once."""
    raw = (raw or "").strip().strip('"')
    s = settings.load()
    if not raw:
        s["backup_copy_dir"] = ""
        settings.save(s)
        _write_status()
        return True, "Вторая копия выключена."
    target = Path(raw)
    try:
        if target.resolve() == backup_dir().resolve():
            return False, "Это та же папка, где лежат основные копии: выберите другое место (другой диск или сетевую папку)."
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".trs398_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return False, f"В эту папку нельзя записывать: {e}"
    s["backup_copy_dir"] = str(target)
    settings.save(s)
    _write_status()
    files = sorted(backup_dir().glob(PATTERN), key=lambda p: p.stat().st_mtime)
    ok = copy_out(files[-1]) if files else True
    if ok is False:
        return False, "Папка сохранена, но копия в неё не записалась: " + (external_status().get("error") or "")
    return True, "Папка сохранена, последняя копия записана." if files else "Папка сохранена, копия появится при следующем резервном копировании."


def keep_days() -> int:
    try:
        return max(1, int(os.environ.get("BACKUP_KEEP_DAYS") or settings.load()["backup_keep_days"]))
    except (ValueError, TypeError):
        return 30


def verify(path: Path) -> dict:
    """Open a backup the way a restore would (unpack, integrity check, count the measurements): {'ok', 'measurements', 'error'}."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "check.db"
            with gzip.open(path, "rb") as f_in, open(plain, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            conn = sqlite3.connect(plain)
            try:
                verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
                n = conn.execute("SELECT count(*) FROM measurement_sessions").fetchone()[0]
            finally:
                conn.close()
        if verdict != "ok":
            return {"ok": False, "measurements": None, "error": str(verdict)[:200]}
        return {"ok": True, "measurements": n, "error": None}
    except (OSError, EOFError, gzip.BadGzipFile, sqlite3.Error) as e:
        return {"ok": False, "measurements": None, "error": str(e)[:200]}


def _verify_file() -> Path:
    return db.data_dir() / "backup_verify.json"


def verify_status(name: str | None = None) -> dict | None:
    """The result of the last check of a backup made by this program (None if it was made before checks existed or for another file)."""
    try:
        st = json.loads(_verify_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return st if name is None or st.get("name") == name else None


def make(now: datetime | None = None, folder: Path | None = None, name_prefix: str = "trs398") -> Path:
    """A compressed copy of the database right now; copies older than the keeping period are removed. Returns its path."""
    now = now or datetime.now()
    default_folder = backup_dir()
    folder = folder or default_folder
    target = folder / f"{name_prefix}_{now:%Y-%m-%d_%H%M%S}.db.gz"
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
        check = verify(target)                           # a backup that cannot be read back is worse than none: it is not kept
        try:
            _verify_file().write_text(json.dumps({"name": target.name, "when": datetime.now().isoformat(timespec="seconds"), **check}), encoding="utf-8")
        except OSError:
            pass
        if not check["ok"]:
            target.unlink(missing_ok=True)
            raise OSError(f"the new backup did not pass the check and was removed: {check['error']}")
        cutoff = time.time() - keep_days() * 86400
        for old in folder.glob(PATTERN):
            if old != target and old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
    if folder == default_folder:                         # the safety copies of restore (folder keep/) are not copied out
        copy_out(target)
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
            "count": len(files), "stale": stale, "verified": verify_status(newest.name),
            "message": ("Последняя резервная копия старше 36 часов: программа должна быть запущена в течение дня." if stale
                        else "Резервная копия свежая.")}


def due(now: datetime | None = None) -> bool:
    """A daily copy is due when the hour of the day (BACKUP_HOUR, local time) has come and today's copy does not exist yet."""
    now = now or datetime.now()
    try:
        hour = int(os.environ.get("BACKUP_HOUR") or settings.load()["backup_hour"])
    except (ValueError, TypeError):
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
                    made = make()
                    db.system_event("backup_auto", "backups", None, {"file": made.name})
                    health.check()                                           # the live file is checked once a day, too
            except Exception as e:                 # a failed copy must never stop the program; the page of backups shows that it is stale
                log.exception("the daily backup failed")
                db.system_event("backup_failed", "backups", None, {"error": str(e)[:200]})
            time.sleep(interval_s)
    t = threading.Thread(target=loop, name="trs398-backup", daemon=True)
    t.start()
    return t
