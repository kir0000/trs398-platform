"""Check that the newest backup can really be restored: load it into a scratch database inside the running
database container and compare row counts with the live database. The live database is only read.

    python tools/verify_backup.py [backups-folder]

Exit code 0: the dump restored; a dump less than 10 minutes old must also match the live counts exactly (older dumps may differ
legitimately, the differences are listed).
"""
import gzip
import subprocess
import sys
import time
from pathlib import Path

CONTAINER = "trs398_db"
SCRATCH = "trs398_verify"
TABLES = ("users", "linacs", "beams", "chamber_units", "calibrations", "electrometers", "measurement_sessions",
          "results", "legacy_journal", "spc_baseline", "audit_log")


def psql(db, sql, stdin=None):
    cmd = ["docker", "exec", "-i", CONTAINER, "psql", "-U", "trs_owner", "-d", db, "-v", "ON_ERROR_STOP=1", "-tA"]
    if stdin is None:
        cmd += ["-c", sql]
    r = subprocess.run(cmd, input=stdin, capture_output=True)
    if r.returncode:
        raise SystemExit(f"psql failed ({db}): {r.stderr.decode('utf-8', 'replace')[:400]}")
    return r.stdout.decode("utf-8", "replace").strip()


def counts(db):
    sql = " UNION ALL ".join(f"SELECT '{t}', count(*) FROM {t}" for t in TABLES)
    return {line.split("|")[0]: int(line.split("|")[1]) for line in psql(db, sql).splitlines()}


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "backups"
    files = sorted(folder.glob("trs398_*.sql.gz"))
    if not files:
        raise SystemExit(f"no backups in {folder}")
    newest = files[-1]
    print(f"newest backup: {newest.name} ({newest.stat().st_size} bytes), {len(files)} file(s) in {folder}")
    psql("postgres", f"DROP DATABASE IF EXISTS {SCRATCH}")
    psql("postgres", f"CREATE DATABASE {SCRATCH}")
    try:
        with gzip.open(newest, "rb") as f:
            sql = f.read()
        subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "trs_owner", "-d", SCRATCH, "-v", "ON_ERROR_STOP=1", "-q"],
                       input=sql, capture_output=True, check=True)
        restored, live = counts(SCRATCH), counts("trs398")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"restore failed: {e.stderr.decode('utf-8', 'replace')[:600]}")
    finally:
        psql("postgres", f"DROP DATABASE IF EXISTS {SCRATCH}")
    fresh = time.time() - newest.stat().st_mtime < 600          # a dump from the last 10 minutes must equal the live database
    bad = [t for t in TABLES if fresh and restored[t] != live[t]]
    print(f"{'table':24}{'backup':>10}{'live':>10}")
    for t in TABLES:
        print(f"{t:24}{restored[t]:>10}{live[t]:>10}{'   <-- check' if t in bad else ''}")
    if bad:
        raise SystemExit("backup does not match the live database")
    print("OK: the backup restores and matches the live database" if restored == live
          else "OK: the backup restores (the live database differs from it: changes made after the dump)")


if __name__ == "__main__":
    main()
