"""Bring a backup back: the database file is REPLACED by the chosen copy. Close the program first.

    python tools/restore.py [file name in the backups folder | path]     (no argument: choose from the newest)

The database that is being replaced is kept in the folder `keep` of the backups before anything else happens.
"""
import gzip
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import backups, db  # noqa: E402


def choose(arg: str | None) -> Path:
    folder = backups.backup_dir()
    if arg:
        p = Path(arg)
        return p if p.is_file() else folder / arg
    files = sorted(folder.glob(backups.PATTERN), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
    if not files:
        raise SystemExit(f"no backups in {folder}")
    for i, f in enumerate(files, 1):
        print(f"{i:3}  {f.name}  {datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d %H:%M}  {f.stat().st_size // 1024} KB")
    n = input("Number [1 = newest]: ").strip() or "1"
    return files[int(n) - 1]


def main():
    src = choose(sys.argv[1] if len(sys.argv) > 1 else None)
    if not src.is_file():
        raise SystemExit(f"no such backup: {src}")
    if input(f"The database will be REPLACED by {src.name}. Type YES to continue: ").strip() != "YES":
        raise SystemExit("Cancelled.")
    target = db.db_path()
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        new = Path(tmp) / "restored.db"
        with gzip.open(src, "rb") as f_in, open(new, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        c = sqlite3.connect(new)
        verdict = c.execute("PRAGMA integrity_check").fetchone()[0]
        c.close()
        if verdict != "ok":
            raise SystemExit(f"the copy is damaged, nothing was changed: {verdict}")
        if target.exists():                                   # keep what is being replaced
            keep = backups.backup_dir() / "keep"
            keep.mkdir(exist_ok=True)
            try:
                backups.make(folder=keep)
            except Exception as e:
                raise SystemExit(f"cannot save the current database, nothing was changed: {e}")
            print(f"the current database is saved in {keep}")
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        try:
            shutil.move(str(new), str(target))
        except PermissionError:
            raise SystemExit("the database file is in use: close the program and run this again")
    print(f"Restored from {src.name}. Start the program.")


if __name__ == "__main__":
    main()
