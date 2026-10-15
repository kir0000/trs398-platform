"""Make a clean demonstration database for a release: two new linacs and 3 years of monthly measurements.
Demo Linac: 3 photon and 5 electron beams, calibrated at SSD 100 cm. Demo Linac SAD: 3 photon beams calibrated at SAD, reference point at 10 cm
depth (SSD 90 cm), dose as in AAPM TG-51: 1 cGy/MU at dmax, so the expected dose at 10 cm is TMR(10) cGy/MU.

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
SAD_NAME, SAD_MODEL, SAD_SERIAL = "Demo Linac SAD", "Demo Linac SAD (demonstration data)", "0002"
SAD_BEAMS = [("photon", 6, False), ("photon", 10, True), ("photon", 15, False)]
SAD_DEPTH, SAD_SSD = 10.0, 90.0                                      # the reference point: 10 cm, the source-axis distance 100 cm
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


def tmr_at_depth(spec: dict, depth: float = SAD_DEPTH) -> float:
    """TMR at `depth` from the PDD (Mayneord factor from SSD 100 cm), the plausible number of a 10 x 10 field."""
    return round(spec["pdd10"] / 100 * ((100 + depth) / (100 + spec["zmax"])) ** 2, 3)


def make_sad_seeder(sd):
    """The seeder whose beams of the SAD linac are measured at SAD: the dose at the reference point against the expected 1 cGy/MU at dmax."""
    from dataclasses import asdict
    from core import photon as ph

    class SadSeeder(sd.Seeder):
        linac_id = None

        def ensure_beam(self, linac_id, modality, energy, fff):
            self.linac_id = linac_id
            self.is_sad = self.one("SELECT name FROM linacs WHERE id = %s", (linac_id,))["name"] == SAD_NAME
            return super().ensure_beam(linac_id, modality, energy, fff)

        def fill_beam_parameters(self, beam_id, modality, energy, fff):
            super().fill_beam_parameters(beam_id, modality, energy, fff)
            if self.is_sad:
                tmr = tmr_at_depth(sd.PHOTONS[(energy, fff)])
                self.c.execute("""UPDATE beams SET ref_depth = %s, tmr_zref = %s, exp_cgy_mu = %s, exp_zref = %s, exp_source = %s WHERE id = %s""",
                               (SAD_DEPTH, tmr, tmr, SAD_DEPTH, "TG-51: 1 сГр/MU на zmax, пересчёт через TMR(10)", beam_id))

        def photon_record(self, rng, cid, nd_w, kelec, energy, fff, d):
            if not self.is_sad:
                return super().photon_record(rng, cid, nd_w, kelec, energy, fff, d)
            spec = sd.PHOTONS[(energy, fff)]
            tmr = tmr_at_depth(spec)
            p, t, mu = round(min(max(rng.gauss(100.9, 0.8), 98.6), 103.0), 2), round(rng.gauss(22.2, 0.5), 1), 200
            tpr = ph.beam_quality_tpr(fff, spec["pdd10"], spec["pdd20"])
            ratio = 1.0062
            base = dict(chamber_id=cid, nd_w=nd_w, mu=mu, pressure_kpa=p, temp_c=t, v1=-300, v2=-100, tpr=tpr, fff=fff, k_elec=kelec,
                        geometry="SAD", expected_cgy_mu=tmr, zref=SAD_DEPTH, ref_distance_cm=SAD_SSD)
            unit = ph.calculate(ph.PhotonInput(m1=[1.0] * 3, m2=[1 / ratio] * 3, m_plus=[0.9996] * 3, m_minus=[1.0] * 3, **base))
            k_all = unit.m_corrected * mu
            dw_zref = tmr / 100 * (1 + d / 100)                         # Gy/MU at the reference point
            m1 = dw_zref / (nd_w * unit.k_q) * mu / k_all
            m1s = [round(m1 * (1 + rng.gauss(0, 0.0003)), 4) for _ in range(3)]
            m2s, mps, mms = [round(x / ratio, 4) for x in m1s], [round(x * 0.9996, 4) for x in m1s], list(m1s)
            res = asdict(ph.calculate(ph.PhotonInput(m1=m1s, m2=m2s, m_plus=mps, m_minus=mms, **base)))
            field = "10 х 10"
            extra = {"demo": True, "form": {
                "pdd10": str(spec["pdd10"]).replace(".", ","), **({"pdd20": str(spec["pdd20"]).replace(".", ",")} if spec["pdd20"] else {}),
                "geometry": "SAD", "field_size": field, "zref": "10", "ref_distance": "90", "zmax": str(spec["zmax"]).replace(".", ","),
                "dose_rate": str(spec["rate"]), "exp_cgy_mu": str(tmr).replace(".", ","), "exp_source": "TG-51: 1 сГр/MU на zmax, пересчёт через TMR(10)",
                "cal_depth": "5", "cal_rh": "50", "polarity_cal": "−", "polarity_user": "−", "electrometer_range": "Medium",
                "p0": "101,325", "t0": "22", "kelec_separate": "1", "kelec_lab": sd.LAB}}
            values = dict(mu=mu, p=p, t=t, rh=round(rng.gauss(45, 6)), v1=-300, v2=-100, m1=m1s, m2=m2s, mp=mps, mm=mms, quality=tpr, pdd=None,
                          geometry="SAD", ref_key=f"SAD|z={SAD_DEPTH:g}|10 x 10|{tmr:g}")
            return values, res, extra

    return SadSeeder


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

    sd.LINACS = [(NAME, MODEL, SERIAL, PHOTON_BEAMS + ELECTRON_BEAMS), (SAD_NAME, SAD_MODEL, SAD_SERIAL, SAD_BEAMS)]
    sd.SETS = {NAME: sd.SETS["TrueBeam"], SAD_NAME: {"photon": sd.SETS["Versa HD"]["photon"]}}
    sd.ELECTRONS[18] = dict(r50=7.55, pdd=98.6, zmax=2.4)
    sd.LINKED = {}
    sd.OVERRIDES = {}
    order = PHOTON_BEAMS + ELECTRON_BEAMS + SAD_BEAMS

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
        summary = make_sad_seeder(sd)(conn).run(months, end, linked=False)
        conn.commit()
    assert len(summary["beams"]) == len(order) and not summary["skipped"], summary
    a.out.mkdir(parents=True, exist_ok=True)
    path = backups.make(folder=a.out, name_prefix="trs398_demo")
    print(f"{summary['sessions']} measurements on {len(summary['beams'])} beams, {months} months up to {end:%Y-%m}")
    print("written:", path)
    print("load it into a copy of the program: load-test-db.bat (portable) or the tray command «Восстановить из копии…»; the first start asks for the administrator.")


if __name__ == "__main__":
    main()
