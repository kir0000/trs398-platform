"""State of the automatic backups, as seen from the application (the folder is mounted read-only)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

STALE_AFTER = timedelta(hours=36)


def backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR", "/backups"))


def recent(limit: int = 15) -> list[dict]:
    """The newest dumps (name, when, size_kb) and the safety copies kept by restore (folder keep/)."""
    folder = backup_dir()
    out = []
    for pattern, kind in (("trs398_*.sql.gz", "авто"), ("keep/*.sql.gz", "сохранённая")):
        for p in folder.glob(pattern) if folder.is_dir() else []:
            out.append({"name": p.relative_to(folder).as_posix(), "when": datetime.fromtimestamp(p.stat().st_mtime),
                        "size_kb": max(1, p.stat().st_size // 1024), "kind": kind})
    return sorted(out, key=lambda r: r["when"], reverse=True)[:limit]


def request_now() -> bool:
    """Ask the backup service for a dump right now (it polls the folder `requests`). False if the folder is not writable."""
    try:
        d = backup_dir() / "requests"
        d.mkdir(exist_ok=True)
        (d / "backup-now").write_text(datetime.now().isoformat(), encoding="utf-8")
        return True
    except OSError:
        return False


def latest(now: datetime | None = None) -> dict:
    """{'found': bool, 'name', 'when', 'size_kb', 'count', 'stale', 'message'} for the newest dump."""
    now = now or datetime.now()
    folder = backup_dir()
    files = sorted(folder.glob("trs398_*.sql.gz"), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
    if not files:
        return {"found": False, "stale": True, "count": 0,
                "message": "Резервных копий нет. Перед удалением данных сделайте копию вручную "
                           "(команда в README) и проверьте службу trs398_backup."}
    newest = files[-1]
    when = datetime.fromtimestamp(newest.stat().st_mtime)
    stale = now - when > STALE_AFTER
    return {"found": True, "name": newest.name, "when": when, "size_kb": max(1, newest.stat().st_size // 1024),
            "count": len(files), "stale": stale,
            "message": ("Последняя резервная копия старше 36 часов: проверьте службу trs398_backup." if stale
                        else "Резервная копия свежая.")}
