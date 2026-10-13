r"""Make a file with the current database that can be loaded into another copy of the program (another laptop, the portable version).

    python tools/make_transfer.py [--source <data folder or .db>] [--out <folder>]

Writes <out>/trs398_<date>_<time>.db.gz (the same format as the backups, checked for integrity) and tells what to do next.
The source is, in this order: --source, the folder TRS_DATA, the data of the installed program (%LOCALAPPDATA%\TRS398\data),
the folder data of the project. Default of --out: the folder `transfer` in the data folder. The file holds the users and the hashes
of their passwords: do not leave it in a shared place longer than needed.
"""
import argparse
import gzip
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def find_source(arg: str | None) -> Path:
    candidates = []
    if arg:
        candidates.append(Path(arg))
    if os.environ.get("TRS_DATA"):
        candidates.append(Path(os.environ["TRS_DATA"]))
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "TRS398" / "data")
    candidates.append(Path(__file__).resolve().parent.parent / "data")
    for c in candidates:
        db = c if c.is_file() else c / "trs398.db"
        if db.is_file():
            return db
    raise SystemExit("no database found: give --source <data folder or trs398.db>")


def make(source: Path, out: Path, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"trs398_{now:%Y-%m-%d_%H%M%S}.db.gz"
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.db"
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        dst = sqlite3.connect(copy)
        try:
            src.backup(dst)                                    # a consistent snapshot, the program may keep running
        finally:
            dst.close()
            src.close()
        check = sqlite3.connect(copy)
        verdict = check.execute("PRAGMA integrity_check").fetchone()[0]
        n = check.execute("SELECT count(*) FROM measurement_sessions").fetchone()[0]
        check.close()
        if verdict != "ok":
            raise SystemExit(f"the database is damaged: {verdict}")
        with open(copy, "rb") as f_in, gzip.open(target, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    print(f"measurements in the file: {n}")
    return target


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source")
    ap.add_argument("--out")
    a = ap.parse_args()
    source = find_source(a.source)
    out = Path(a.out) if a.out else source.parent / "transfer"
    path = make(source, out)
    print(f"source: {source}")
    print(f"file:   {path} ({path.stat().st_size // 1024} KB)")
    print("\nOn the other computer: put the file into the folder of the program (next to TRS398.exe) or into its `transfer` folder\n"
          "and double-click load-test-db.bat, or: TRS398.exe restore <file>. The database there is REPLACED (a copy of it is kept in backups/keep).")


if __name__ == "__main__":
    main()
