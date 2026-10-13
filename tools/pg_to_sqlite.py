"""Move the data of the PostgreSQL edition (1.x, Docker) into a new SQLite database of version 2.

    python tools/pg_to_sqlite.py --env-file .env [--pg-port 5433] [--out data/trs398.db] [--force]
    python tools/pg_to_sqlite.py --pg-url postgresql://user:pass@localhost:5433/trs398 --out new.db

The PostgreSQL database is only read. The new file gets the schema of version 2 (app/migrations), every table is copied with its
identifiers (so the references and the protocol numbers stay as they were), then the copy is verified: row counts, every value
of every table, and the rows of the trend view. Exit code 0 only when everything matches.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

SKIP = {"schema_migrations", "_maintenance"}


def pg_url(args) -> str:
    if args.pg_url:
        return args.pg_url
    pwd = None
    if args.env_file:
        for line in Path(args.env_file).read_text(encoding="utf-8").splitlines():
            if line.startswith("TRS_OWNER_PASSWORD="):
                pwd = line.split("=", 1)[1].strip()
    if not pwd:
        raise SystemExit("give --pg-url, or --env-file with TRS_OWNER_PASSWORD")
    return f"postgresql://trs_owner:{pwd}@127.0.0.1:{args.pg_port}/trs398"


def to_sqlite(v):
    """A PostgreSQL value as it is stored in the SQLite file (see app/db.py for the way back)."""
    if v is None or isinstance(v, (int, str)):
        return int(v) if isinstance(v, bool) else v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dt.datetime):
        if v.tzinfo:
            v = v.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (list, dict, tuple)):
        return json.dumps(v, ensure_ascii=False, default=float)
    return v


def same(a, b) -> bool:
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= 1e-12 * max(1.0, abs(float(a)))
    if isinstance(a, (list, tuple)) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, dt.datetime) and isinstance(b, dt.datetime):
        return a.astimezone(dt.timezone.utc).replace(microsecond=0) == b.astimezone(dt.timezone.utc).replace(microsecond=0)   # stored to the second
    return a == b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    ap.add_argument("--pg-url")
    ap.add_argument("--pg-port", type=int, default=5433)
    ap.add_argument("--out", default=str(db.db_path()))
    ap.add_argument("--force", action="store_true", help="replace an existing output file")
    args = ap.parse_args()

    import psycopg
    out = Path(args.out)
    if out.exists():
        if not args.force:
            raise SystemExit(f"{out} exists; use --force to replace it")
        for suffix in ("", "-wal", "-shm"):
            Path(str(out) + suffix).unlink(missing_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)

    pg = psycopg.connect(pg_url(args))
    pg.read_only = True
    lite = db.connect(out)
    db.migrate(lite)
    lite.commit()

    tables = [r["name"] for r in lite.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
              if r["name"] not in SKIP]
    pg_tables = {r[0] for r in pg.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'").fetchall()}
    lite.execute("PRAGMA foreign_keys = OFF")                       # the tables are copied in any order; checked at the end
    problems: list[str] = []
    cols_of: dict[str, list[str]] = {}
    for t in tables:
        if t not in pg_tables:
            print(f"  {t:24} not in PostgreSQL, left empty")
            continue
        lite_cols = [r["name"] for r in lite.execute(f"PRAGMA table_info({t})").fetchall()]
        pg_cols = {r[0] for r in pg.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", (t,)).fetchall()}
        cols = [c for c in lite_cols if c in pg_cols]
        for c in pg_cols - set(lite_cols):
            problems.append(f"{t}.{c} exists in PostgreSQL but not in the new schema (not copied)")
        cols_of[t] = cols
        rows = pg.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall()
        lite.execute("BEGIN IMMEDIATE") if not lite.in_transaction else None
        lite.executemany(f"INSERT INTO {t}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         [tuple(to_sqlite(v) for v in r) for r in rows])
        lite.commit()
        print(f"  {t:24} {len(rows):6} rows")

    # ---- verification
    bad = lite.execute("PRAGMA foreign_key_check").fetchall()
    for r in bad[:10]:
        problems.append(f"foreign key: {tuple(r.values()) if isinstance(r, dict) else tuple(r)}")
    lite.execute("PRAGMA foreign_keys = ON")
    lite.row_factory = lambda cur, row: tuple(db._convert(d[0], v) for d, v in zip(cur.description, row))
    for t, cols in cols_of.items():
        order = "id" if "id" in cols else ("year" if "year" in cols else cols[0])
        sel = f"SELECT {', '.join(cols)} FROM {t} ORDER BY {order}"
        a = pg.execute(sel).fetchall()
        b = lite.execute(sel).fetchall()
        if len(a) != len(b):
            problems.append(f"{t}: {len(a)} rows in PostgreSQL, {len(b)} in SQLite")
            continue
        n_bad = 0
        for ra, rb in zip(a, b):
            for c, x, y in zip(cols, ra, rb):
                if isinstance(x, bool) and isinstance(y, int):
                    y = bool(y)
                if not same(x, y):
                    n_bad += 1
                    if n_bad <= 3:
                        problems.append(f"{t}.{c}: PostgreSQL {x!r} / SQLite {y!r}")
        if n_bad > 3:
            problems.append(f"{t}: {n_bad} differing values in total")

    # the view the trends are drawn from: the same rows with the same numbers
    key = "source, record_id"
    cols = "source, record_id, measured_on, linac, modality, nominal_energy, fff, dw_zmax, deviation_pct, ref_key"
    try:
        a = pg.execute(f"SELECT {cols} FROM v_trend ORDER BY {key}").fetchall()
        b = lite.execute(f"SELECT {cols} FROM v_trend ORDER BY {key}").fetchall()
        if len(a) != len(b) or not all(same(list(x), list(y)) for x, y in zip(a, b)):
            first = next((f"{x} / {y}" for x, y in zip(a, b) if not same(list(x), list(y))), "")
            problems.append(f"v_trend differs ({len(a)} / {len(b)} rows): {first}")
        else:
            print(f"  v_trend                  {len(a):6} rows equal")
    except Exception as e:                                          # an old 1.x schema without ref_key etc.
        problems.append(f"v_trend not compared: {e}")

    lite.close()
    pg.close()
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"\nOK: {out} is a verified copy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
