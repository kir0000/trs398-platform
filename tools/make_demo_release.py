"""Make a clean demonstration database for a release: nothing but one new linac (3 photon and 5 electron beams) and 3 years of monthly measurements.

    python tools/make_demo_release.py [--out <folder>] [--years 3] [--end YYYY-MM-DD]

Every beam drifts away from the nominal output by up to 3 % (the sign differs from beam to beam), is re-adjusted and stays near 0 afterwards.
The database is built from scratch in a temporary folder (the database of the program is never touched), there are no working accounts (only the two inactive, locked demo authors of the records): the person
who loads the file creates the administrator at the first start. Writes <out>/trs398_demo_<date>.db.gz (default folder: `transfer` of the project),
which loads like any backup: load-test-db.bat of the portable copy, or the tray command «Восстановить из копии…».
"""
import argparse
import datetime as dt
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

NAME, MODEL, SERIAL = "Demo Linac", "Demo Linac (demonstration data)", "0001"
PHOTON_BEAMS = [("photon", 6, False), ("photon", 6, True), ("photon", 10, True)]
ELECTRON_BEAMS = [("electron", e, False) for e in (6, 9, 12, 15, 18)]
PEAKS = [3.0, 2.6, 2.9, 2.4, 3.0, 2.7, 2.5, 2.8]                    # the largest deviation of each beam before its re-adjustment, %


def drift_series(rng: random.Random, months: int, sign: int, peak: float, kinds: dict) -> list[tuple[float, str]]:
    """(deviation %, kind): a steady drift to `sign * peak`, the re-adjustment, then the output stays near 0."""
    length = rng.randint(11, 16)
    out = []
    near = 0.0
    for i in range(months):
        if i < length:
            level = sign * peak * (i + 1) / length
            kind = "event" if abs(level) >= 2.0 and (i == 0 or abs(out[-1][0]) < 2.0 - 0.3) else "plan"
            out.append((round(level + rng.gauss(0, 0.12), 3), kind))
        elif i == length:
            near = rng.uniform(-0.12, 0.12)
            out.append((round(near + rng.gauss(0, 0.08), 3), "adjust"))
        else:
            near = 0.85 * near + rng.gauss(0, 0.07)                 # a bounded wander around 0
            out.append((round(near + rng.gauss(0, 0.12), 3), "plan"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "transfer")
    ap.add_argument("--years", type=float, default=3)
    ap.add_argument("--end", type=dt.date.fromisoformat, default=None, help="month of the last record (default: the latest month already past its 15th)")
    a = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="trs398_demo_"))
    os.environ["TRS_DB"] = str(work / "trs398.db")
    os.environ["TRS_DATA"] = str(work)
    os.environ["BACKUP_DIR"] = str(work / "backups")
    os.environ["TRS_NO_SCHEDULER"] = "1"

    import seed_demo as sd
    from app import backups, db as appdb, services

    sd.LINACS = [(NAME, MODEL, SERIAL, PHOTON_BEAMS + ELECTRON_BEAMS)]
    sd.SETS = {NAME: sd.SETS["TrueBeam"]}
    sd.ELECTRONS[18] = dict(r50=7.55, pdd=98.6, zmax=2.4)
    sd.LINKED = {}
    sd.OVERRIDES = {}
    order = {b: i for i, b in enumerate(PHOTON_BEAMS + ELECTRON_BEAMS)}

    def series(rng, months, **_ignored):                        # the seeder asks for one series per beam, in the order of the beams
        series.n += 1
        i = series.n - 1
        return drift_series(rng, months, 1 if i % 2 == 0 else -1, PEAKS[i % len(PEAKS)], {})
    series.n = 0
    sd.deviation_series = series
    sd.RESERVE = []                                             # a clean list of equipment: only what the demonstration uses

    months = round(a.years * 12)
    end = a.end or sd.default_end(dt.date.today())
    with appdb.connect() as conn:
        appdb.migrate(conn)
        services.seed_chambers(conn)
        summary = sd.Seeder(conn).run(months, end, linked=False)
        conn.commit()
    assert len(summary["beams"]) == len(order) and not summary["skipped"], summary
    a.out.mkdir(parents=True, exist_ok=True)
    path = backups.make(folder=a.out, name_prefix="trs398_demo")
    print(f"{summary['sessions']} measurements on {len(summary['beams'])} beams, {months} months up to {end:%Y-%m}")
    print("written:", path)
    print("load it into a copy of the program: load-test-db.bat (portable) or the tray command «Восстановить из копии…»; the first start asks for the administrator.")


if __name__ == "__main__":
    main()
