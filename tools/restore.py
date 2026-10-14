"""Bring a backup back: the database file is REPLACED by the chosen copy. Close the program first.

    python tools/restore.py [file | folder | name in the backups folder] [--yes]
        file    a backup (trs398_*.db.gz) or a plain database file (*.db); a folder: the newest backup in it
        --yes   do not ask for the confirmation (used by load-test-db.bat)
    (no argument: choose from the newest backups of the program)

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


def newest_in(folder: Path) -> Path | None:
    files = sorted(folder.glob(backups.PATTERN), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def choose(arg: str | None) -> Path:
    folder = backups.backup_dir()
    if arg:
        p = Path(arg)
        if p.is_dir():
            found = newest_in(p) or newest_in(p / "transfer")
            if not found:
                raise SystemExit(f"no backups (trs398_*.db.gz) in {p}")
            return found
        return p if p.is_file() else folder / arg
    files = sorted(folder.glob(backups.PATTERN), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
    if not files:
        raise SystemExit(f"no backups in {folder}")
    for i, f in enumerate(files, 1):
        print(f"{i:3}  {f.name}  {datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d %H:%M}  {f.stat().st_size // 1024} KB")
    n = input("Number [1 = newest]: ").strip() or "1"
    return files[int(n) - 1]


def unpack(src: Path, dest: Path) -> None:
    """A backup (gzip) or a plain SQLite file into dest."""
    with open(src, "rb") as f:
        magic = f.read(16)
    if magic.startswith(b"SQLite format 3"):
        shutil.copyfile(src, dest)
        return
    with gzip.open(src, "rb") as f_in, open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def main():
    args = [a for a in sys.argv[1:] if a != "--yes"]
    src = choose(args[0] if args else None)
    if not src.is_file():
        raise SystemExit(f"no such backup: {src}")
    if "--yes" not in sys.argv[1:] and input(f"The database will be REPLACED by {src.name}. Type YES to continue: ").strip() != "YES":
        raise SystemExit("Cancelled.")
    target = db.db_path()
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        new = Path(tmp) / "restored.db"
        unpack(src, new)
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
                print(f"the current database is saved in {keep}")
            except Exception as e:                                # a damaged file cannot be copied by SQLite: keep the bytes as they are
                aside = keep / f"trs398_damaged_{datetime.now():%Y-%m-%d_%H%M%S}.db"
                try:
                    shutil.copyfile(target, aside)
                except OSError as e2:
                    raise SystemExit(f"cannot save the current database, nothing was changed: {e} / {e2}")
                print(f"the current database could not be copied normally ({e}); the file is kept as it is: {aside}")
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        try:
            shutil.move(str(new), str(target))
        except PermissionError:
            raise SystemExit("the database file is in use: close the program and run this again")
    try:                                                      # the program writes the record into the restored database at its start
        import json
        (target.parent / "restored.json").write_text(json.dumps({"file": src.name, "at": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    except OSError:
        pass
    print(f"Restored from {src.name}. Start the program.")


if __name__ == "__main__":
    main()
