"""Check that the newest backup can really be restored: unpack it into a scratch file, run the integrity check and compare row
counts with the live database (the live database is only read).

    python tools/verify_backup.py [backups-folder]

Exit code 0: the copy opens and is intact; a copy less than 10 minutes old must also match the live counts exactly.
"""
import gzip
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import backups, db  # noqa: E402

TABLES = ("users", "linacs", "beams", "chamber_units", "calibrations", "electrometers", "measurement_sessions",
          "results", "legacy_journal", "spc_baseline", "audit_log")


def counts(path) -> dict:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        c.close()


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else backups.backup_dir()
    files = sorted(folder.glob(backups.PATTERN), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"no backups in {folder}")
    newest = files[-1]
    print(f"newest backup: {newest.name} ({newest.stat().st_size} bytes), {len(files)} file(s) in {folder}")
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "check.db"
        with gzip.open(newest, "rb") as f_in, open(scratch, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        c = sqlite3.connect(scratch)
        verdict = c.execute("PRAGMA integrity_check").fetchone()[0]
        c.close()
        if verdict != "ok":
            raise SystemExit(f"the copy is damaged: {verdict}")
        restored = counts(scratch)
    live = counts(db.db_path())
    fresh = time.time() - newest.stat().st_mtime < 600
    bad = [t for t in TABLES if fresh and restored[t] != live[t]]
    print(f"{'table':24}{'backup':>10}{'live':>10}")
    for t in TABLES:
        print(f"{t:24}{restored[t]:>10}{live[t]:>10}{'   <-- check' if t in bad else ''}")
    if bad:
        raise SystemExit("backup does not match the live database")
    print("OK: the backup is intact and matches the live database" if restored == live
          else "OK: the backup is intact (the live database differs from it: changes made after the copy)")


if __name__ == "__main__":
    main()
