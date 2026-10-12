"""Fill the database with demo measurements for several linacs and energies (two years, monthly).
The notes and the demo user names are Russian data; the English interface translates them through the phrase catalog.

Equipment: TrueBeam follows the user's worksheet templates 2.0 (photons SNC600c Farmer, ND,w = 0.05138 Gy/nC, V1 = -300 V;
electrons PTW 34001 Roos, ND,w = 0.5791 Gy/nC, V1 = +300 V); Versa HD has its own chambers (PTW 30013 Farmer, IBA NACP-02) and
electrometer; two reserve chambers (IBA FC65-G, a second PTW 34001 Roos) are registered with calibrations. Each record is a real approved measurement
(raw readings, results computed by the same core as the application), marked DEMO, created by the inactive user
"Демо-физик" and approved by "Демо-проверяющий". Output deviations follow a plausible process: noise, slow drift, an
occasional jump out of tolerance and a re-adjustment afterwards.

    python tools/seed_demo.py              # add demo data (idempotent, beams with real data are skipped)
    python tools/seed_demo.py --remove     # remove only what this script added

Connection: DATABASE_URL, or built from TRS_OWNER_PASSWORD in .env (owner role: seeding writes approved records
directly, which the application role cannot do).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
from dataclasses import asdict
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import services                                         # noqa: E402
from core import electron as el                                   # noqa: E402
from core import photon as ph                                     # noqa: E402

LINACS = [
    ("TrueBeam", "Varian TrueBeam", "2480",
     [("photon", 6, False), ("photon", 6, True), ("photon", 10, True),
      ("electron", 6, False), ("electron", 9, False), ("electron", 12, False), ("electron", 15, False)]),
    ("Versa HD", "Elekta Versa HD", "7213",
     [("photon", 6, False), ("photon", 6, True), ("photon", 10, True), ("photon", 15, False),
      ("electron", 6, False), ("electron", 9, False), ("electron", 12, False), ("electron", 15, False)]),
]
# typical beam data: PDD(10)/PDD(20) at SSD 100 cm, dose rate, zmax; electrons: R50 (ionisation), PDD(zref)
PHOTONS = {
    (6, False): dict(pdd10=66.6, pdd20=38.2, zmax=1.5, rate=600),
    (6, True): dict(pdd10=63.3, pdd20=None, zmax=1.3, rate=1400),
    (10, True): dict(pdd10=70.5, pdd20=None, zmax=2.2, rate=2400),
    (15, False): dict(pdd10=77.0, pdd20=51.5, zmax=2.9, rate=600),
}
ELECTRONS = {
    6: dict(r50=2.45, pdd=100.0, zmax=1.3), 9: dict(r50=3.75, pdd=100.0, zmax=2.0),
    12: dict(r50=5.0, pdd=99.6, zmax=2.6), 15: dict(r50=6.3, pdd=99.2, zmax=2.9),
}
D = dt.date
UNIDOS, DOSE1 = ("PTW UNIDOS E", "1234"), ("IBA Dose1", "5678")
# chambers and calibrations per linac (the values are plausible demonstration values, not a certificate):
# TrueBeam follows the worksheet templates 2.0, Versa HD has its own chambers and electrometer
SETS = {
    "TrueBeam": {
        "photon": dict(chamber="Sun Nuclear SNC600c Farmer", sn="123456789", electrometer=UNIDOS,
                       cals=[(D(2024, 2, 1), D(2026, 2, 1), 0.05152, 0.9995), (D(2026, 2, 1), D(2028, 2, 1), 0.05138, 0.9987)]),
        "electron": dict(chamber="PTW 34001 Roos", sn="123456789", electrometer=UNIDOS,
                         cals=[(D(2024, 2, 1), D(2026, 2, 1), 0.5805, 1.0), (D(2026, 2, 1), D(2028, 2, 1), 0.5791, 1.0)]),
    },
    "Versa HD": {
        "photon": dict(chamber="PTW 30013 Farmer", sn="3047", electrometer=DOSE1,
                       cals=[(D(2024, 3, 1), D(2026, 3, 1), 0.05386, 0.9992), (D(2026, 3, 1), D(2028, 3, 1), 0.05371, 0.9990)]),
        "electron": dict(chamber="IBA NACP-02", sn="2561", electrometer=DOSE1,
                         cals=[(D(2024, 3, 1), D(2026, 3, 1), 0.6354, 1.0), (D(2026, 3, 1), D(2028, 3, 1), 0.6331, 1.0)]),
    },
}
# reserve chambers: registered with a valid calibration (selectable in the form), no demonstration records
RESERVE = [
    ("photon", dict(chamber="IBA FC65-G Farmer", sn="3119", electrometer=UNIDOS, cals=[(D(2026, 5, 10), D(2028, 5, 10), 0.05312, 0.9987)])),
    ("electron", dict(chamber="PTW 34001 Roos", sn="3320", electrometer=UNIDOS, cals=[(D(2026, 5, 10), D(2028, 5, 10), 0.5822, 1.0)])),
]
LAB = "ВНИИФТРИ"
DEMO_USERS = (("demo_phys", "Демо-физик", "physicist"), ("demo_rev", "Демо-проверяющий", "reviewer"))
NOTES = {"plan": "DEMO: плановая проверка", "event": "DEMO: отклонение вне допуска, назначена перепроверка",
         "adjust": "DEMO: настройка выходной дозы", "common": "DEMO: общий сдвиг после обслуживания монитора"}
# a common cause: all energies of a linac move together for a while (month index counted from the first record)
COMMON_EVENTS = {"TrueBeam": [(17, 0.7), (18, 0.7)]}


def month_start(d: dt.date, back: int) -> dt.date:
    m = d.year * 12 + d.month - 1 - back
    return dt.date(m // 12, m % 12 + 1, 1)


# two scenarios are fixed on purpose so that the demo always contains something to look at
OVERRIDES = {
    ("Versa HD", "photon", 6, False): dict(event=14, jump=2.7),            # out of tolerance, then re-adjusted
    ("TrueBeam", "electron", 12, False): dict(event=None, drift=0.045),    # slow drift, no jump: shows trend and forecast
}


def deviation_series(rng: random.Random, months: int, event="random", jump=None, drift=None, common=None):
    """(deviation %, kind) per month: noise + drift, maybe a jump out of tolerance followed by a re-adjustment."""
    level = rng.uniform(-0.12, 0.18)
    drift_ = rng.uniform(-0.008, 0.014)
    sigma = rng.uniform(0.15, 0.27)
    event_ = rng.randrange(9, 18) if rng.random() < 0.6 else None
    jump_ = rng.choice([1.5, 2.2, 2.8])
    if event != "random":
        event_ = event
    if jump is not None:
        jump_ = jump
    if drift is not None:
        drift_ = drift
    out = []
    for i in range(months):
        kind = "plan"
        level += drift_
        if event_ is not None and i == event_:
            level += jump_
            kind = "event"
        elif event_ is not None and i == event_ + 1:
            level = rng.uniform(-0.1, 0.1)
            kind = "adjust"
        out.append((round(level + rng.gauss(0, sigma), 3), kind))
    for idx, shift in common or []:                       # added after all random draws, so the other series do not change
        if idx < months:
            out[idx] = (round(out[idx][0] + shift, 3), out[idx][1] if out[idx][1] != "plan" else "common")
    return out


class Seeder:
    def __init__(self, conn):
        self.c = conn
        self.created = dict(beams=[], calibrations=[], units=[], electrometers=[], users=[], linac_fields=[], beam_fields=[])

    # ---- helpers
    def one(self, sql, args=()):
        return self.c.execute(sql, args).fetchone()

    def ensure_users(self):
        ids = {}
        for login, name, role in DEMO_USERS:
            row = self.one("SELECT id FROM users WHERE login = %s", (login,))
            if not row:
                row = self.one("INSERT INTO users(login, full_name, role, password_hash, is_active) "
                               "VALUES (%s, %s, %s, '!locked-demo-account', false) RETURNING id", (login, name, role))
                self.created["users"].append(row["id"])
            ids[login] = row["id"]
        return ids["demo_phys"], ids["demo_rev"]

    def ensure_calibrations(self, modality, spec):
        chamber = spec["chamber"]
        chamber_id = self.one("SELECT id FROM chambers WHERE name = %s", (chamber,))["id"]
        unit = self.one("SELECT id FROM chamber_units WHERE chamber_id = %s AND serial_no = %s", (chamber_id, spec["sn"]))
        if not unit:
            unit = self.one("INSERT INTO chamber_units(chamber_id, serial_no) VALUES (%s, %s) RETURNING id",
                            (chamber_id, spec["sn"]))
            self.created["units"].append(unit["id"])
        emod, esn = spec["electrometer"]
        em = self.one("SELECT id FROM electrometers WHERE model = %s AND serial_no = %s", (emod, esn))
        if not em:
            em = self.one("INSERT INTO electrometers(model, serial_no) VALUES (%s, %s) RETURNING id", (emod, esn))
            self.created["electrometers"].append(em["id"])
        out = []
        for on, valid, nd_w, kelec in spec["cals"]:
            row = self.one("SELECT id FROM calibrations WHERE chamber_unit_id = %s AND calibrated_on = %s", (unit["id"], on))
            if row:
                photon = modality == "photon"
                self.c.execute("""UPDATE calibrations SET q0 = COALESCE(q0, 'Co-60'), cal_depth = COALESCE(cal_depth, 5),
                    p0 = COALESCE(p0, 101.325), t0 = COALESCE(t0, %s), cal_rh = COALESCE(cal_rh, 50),
                    polarity_cal = COALESCE(polarity_cal, %s), polarity_user = COALESCE(polarity_user, %s),
                    el_range = COALESCE(el_range, %s), kelec_lab = COALESCE(kelec_lab, %s), kelec_date = COALESCE(kelec_date, %s)
                    WHERE id = %s""", (22 if photon else 20, "−" if photon else "+", "−" if photon else "+",
                                       "Medium" if photon else "средний", LAB if photon else None, on if photon else None,
                                       row["id"]))
            if not row:
                photon = modality == "photon"
                sign = "−" if photon else "+"
                row = self.one("""INSERT INTO calibrations(chamber_unit_id, electrometer_id, nd_w, k_elec, kelec_separate, lab,
                                  calibrated_on, valid_until, voltage_v, q0, cal_depth, p0, t0, cal_rh, polarity_cal,
                                  polarity_user, el_range, kelec_lab, kelec_date)
                                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Co-60', 5, 101.325, %s, 50, %s, %s, %s, %s, %s)
                                  RETURNING id""", (unit["id"], em["id"], nd_w, kelec, photon, LAB, on, valid,
                                                    -300 if photon else 300, 22 if photon else 20, sign, sign,
                                                    "Medium" if photon else "средний", LAB if photon else None,
                                                    on if photon else None))
                self.created["calibrations"].append(row["id"])
            out.append((on, row["id"], nd_w, kelec))
        return out, services.core_chamber_id(modality, chamber)

    def ensure_beam(self, linac_id, modality, energy, fff):
        row = self.one("SELECT id FROM beams WHERE linac_id = %s AND modality = %s AND nominal_energy = %s AND fff = %s",
                       (linac_id, modality, energy, fff))
        if not row:
            row = self.one("INSERT INTO beams(linac_id, modality, nominal_energy, fff) VALUES (%s, %s, %s, %s) RETURNING id",
                           (linac_id, modality, energy, fff))
            self.created["beams"].append(row["id"])
        return row["id"]

    def fill_beam_parameters(self, beam_id, modality, energy, fff):
        """Equipment parameters of the beam (only where empty, so the user's own entries stay)."""
        if modality == "photon":
            spec = PHOTONS[(energy, fff)]
            rate, field, zmax = spec["rate"], "10 х 10", spec["zmax"]
        else:
            rate, field, zmax = 1000, "15х15" if energy >= 9 else "10х10", ELECTRONS[energy]["zmax"]
        row = self.one("SELECT dose_rate_mu, field_size, phantom, zmax FROM beams WHERE id = %s", (beam_id,))
        if all(v is None for v in row.values()):
            self.c.execute("""UPDATE beams SET dose_rate_mu = %s, field_size = %s, phantom = 'водный', c_pl = 1, h_pl = 1,
                              zmax = %s WHERE id = %s""", (rate, field, zmax, beam_id))
            self.created["beam_fields"].append(beam_id)

    def beam_is_free(self, beam_id) -> bool:
        """No real history on the beam: no imported real journal, no approved record that is not demo, and not seeded yet.
        A draft, a submitted or a returned record of the user does not count: it is work in progress."""
        real_legacy = self.one("SELECT count(*) AS n FROM legacy_journal WHERE beam_id = %s AND NOT is_demo", (beam_id,))["n"]
        busy = self.one("""SELECT count(*) AS n FROM measurement_sessions WHERE beam_id = %s
                           AND (extra->>'demo' = 'true' OR status IN ('approved', 'superseded'))""", (beam_id,))["n"]
        return real_legacy == 0 and busy == 0

    # ---- one record
    def insert(self, beam_id, cal_id, phys, rev, on, values, results, extra, note):
        sid = self.one("""INSERT INTO measurement_sessions(measured_on, beam_id, calibration_id, geometry, mu, pressure_kpa,
            temp_c, humidity_pct, v1, v2, m1_readings, m2_readings, m_plus_readings, m_minus_readings, beam_quality, pdd_zref,
            note, status, created_by, approved_by, approved_at, extra)
            VALUES (%s,%s,%s,'SSD',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'approved',%s,%s,%s,%s) RETURNING id""",
                       (on, beam_id, cal_id, values["mu"], values["p"], values["t"], values["rh"], values["v1"], values["v2"],
                        values["m1"], values["m2"], values["mp"], values["mm"], values["quality"], values["pdd"], note,
                        phys, rev, dt.datetime.combine(on + dt.timedelta(days=1), dt.time(10, 0), dt.timezone.utc),
                        Jsonb(extra)))["id"]
        cols = ("k_tp", "k_elec", "k_pol", "k_s", "k_vol", "k_q", "m_corrected", "dw_zref", "dw_zmax", "deviation_pct",
                "formula_version", "tables_version")
        self.c.execute(f"INSERT INTO results(session_id, {', '.join(cols)}) VALUES (%s, {', '.join(['%s'] * len(cols))})",
                       [sid] + [results[k] for k in cols])

    def photon_record(self, rng, cid, nd_w, kelec, energy, fff, d):
        spec = PHOTONS[(energy, fff)]
        p, t, mu = round(min(max(rng.gauss(100.9, 0.8), 98.6), 103.0), 2), round(rng.gauss(22.2, 0.5), 1), 200
        tpr = ph.beam_quality_tpr(fff, spec["pdd10"], spec["pdd20"])
        ratio = 1.0062
        base = dict(chamber_id=cid, nd_w=nd_w, mu=mu, pressure_kpa=p, temp_c=t, v1=-300, v2=-100, tpr=tpr, fff=fff,
                    pdd_zref=spec["pdd10"], k_elec=kelec, geometry="SSD")
        unit = ph.calculate(ph.PhotonInput(m1=[1.0] * 3, m2=[1 / ratio] * 3, m_plus=[0.9996] * 3, m_minus=[1.0] * 3, **base))
        k_all = unit.m_corrected * mu                                  # product of k factors for M1 = 1
        dw_zref = 0.01 * (1 + d / 100) * spec["pdd10"] / 100
        m1 = dw_zref / (nd_w * unit.k_q) * mu / k_all
        series = lambda scale: [round(m1 * scale * (1 + rng.gauss(0, 0.0003)), 4) for _ in range(3)]
        m1s = series(1.0)
        m2s, mps, mms = [round(x / ratio, 4) for x in m1s], [round(x * 0.9996, 4) for x in m1s], list(m1s)
        res = asdict(ph.calculate(ph.PhotonInput(m1=m1s, m2=m2s, m_plus=mps, m_minus=mms, **base)))
        extra = {"demo": True, "form": {
            "pdd10": str(spec["pdd10"]).replace(".", ","), **({"pdd20": str(spec["pdd20"]).replace(".", ",")} if spec["pdd20"] else {}),
            "field_size": "10 х 10", "zref": "10", "zmax": str(spec["zmax"]).replace(".", ","), "dose_rate": str(spec["rate"]),
            "cal_depth": "5", "cal_rh": "50", "polarity_cal": "−", "polarity_user": "−", "electrometer_range": "Medium",
            "p0": "101,325", "t0": "22", "kelec_separate": "1", "kelec_lab": LAB}}
        values = dict(mu=mu, p=p, t=t, rh=round(rng.gauss(45, 6)), v1=-300, v2=-100, m1=m1s, m2=m2s, mp=mps, mm=mms,
                      quality=tpr, pdd=spec["pdd10"])
        return values, res, extra

    def electron_record(self, rng, cid, nd_w, kelec, energy, d):
        spec = ELECTRONS[energy]
        p, t, mu = round(min(max(rng.gauss(100.9, 0.8), 98.6), 103.0), 2), round(rng.gauss(22.2, 0.5), 1), 100
        r50 = round(spec["r50"] + rng.gauss(0, 0.01), 3)
        ratio = 0.9983
        base = dict(chamber_id=cid, nd_w=nd_w, mu=mu, pressure_kpa=p, temp_c=t, v1=300, v2=100, r50_measured=r50,
                    pdd_zref=spec["pdd"], k_elec=kelec)
        unit = el.calculate(el.ElectronInput(m1=[1.0] * 4, m2=[1 / ratio] * 4, m_plus=[0.9996] * 4, m_minus=[1.0] * 4, **base))
        k_all = unit.m_corrected * mu
        dw_zref = 0.01 * (1 + d / 100) * spec["pdd"] / 100
        m1 = dw_zref / (nd_w * unit.k_q) * mu / k_all
        m1s = [round(m1 * (1 + rng.gauss(0, 0.0003)), 4) for _ in range(4)]
        m2s, mps, mms = [round(x / ratio, 4) for x in m1s], [round(x * 0.9996, 4) for x in m1s], list(m1s)
        r = el.calculate(el.ElectronInput(m1=m1s, m2=m2s, m_plus=mps, m_minus=mms, **base))
        res = asdict(r)
        res["k_vol"] = 1.0
        extra = {"demo": True, "r50w": r.r50w, "zref": r.zref, "form": {
            "q0_is_co60": "1", "field_size": "15х15" if energy >= 9 else "10х10", "zmax": str(spec["zmax"]).replace(".", ","),
            "dose_rate": "1000", "cal_depth": "5", "cal_rh": "50", "polarity_cal": "+", "polarity_user": "+",
            "electrometer_range": "средний", "p0": "101,325", "t0": "20"}}
        values = dict(mu=mu, p=p, t=t, rh=round(rng.gauss(45, 6)), v1=300, v2=100, m1=m1s, m2=m2s, mp=mps, mm=mms,
                      quality=r50, pdd=spec["pdd"])
        return values, res, extra

    # ---- whole run
    def run(self, months: int, end: dt.date):
        phys, rev = self.ensure_users()
        cals = {}
        summary = {"sessions": 0, "beams": [], "skipped": []}
        for name, model, serial, beams in LINACS:
            linac = self.one("SELECT id, model, serial_no FROM linacs WHERE name = %s", (name,))
            if not linac:
                linac = self.one("INSERT INTO linacs(name, model, serial_no) VALUES (%s, %s, %s) RETURNING id, model, serial_no",
                                 (name, model, serial))
                self.created.setdefault("linacs", []).append(linac["id"])
            elif not linac["model"] and not linac["serial_no"]:
                self.c.execute("UPDATE linacs SET model = %s, serial_no = %s WHERE id = %s", (model, serial, linac["id"]))
                self.created["linac_fields"].append(linac["id"])
            for modality, energy, fff in beams:
                beam_id = self.ensure_beam(linac["id"], modality, energy, fff)
                self.fill_beam_parameters(beam_id, modality, energy, fff)
                label = f"{name}: {modality} {energy}{' FFF' if fff else ''}"
                if not self.beam_is_free(beam_id):
                    summary["skipped"].append(label)
                    continue
                rng = random.Random(f"{name}|{modality}|{energy}|{fff}")
                if (name, modality) not in cals:
                    cals[(name, modality)] = self.ensure_calibrations(modality, SETS[name][modality])
                calibs, chamber_core_id = cals[(name, modality)]
                for i, (d, kind) in enumerate(deviation_series(rng, months, common=COMMON_EVENTS.get(name),
                                                                 **OVERRIDES.get((name, modality, energy, fff), {}))):
                    on = month_start(end, months - 1 - i).replace(day=15)
                    on_cal = [c for c in calibs if c[0] <= on][-1]
                    _, cal_id, nd_w, kelec = on_cal
                    if modality == "photon":
                        values, res, extra = self.photon_record(rng, chamber_core_id, nd_w, kelec, energy, fff, d)
                    else:
                        values, res, extra = self.electron_record(rng, chamber_core_id, nd_w, kelec, energy, d)
                    self.insert(beam_id, cal_id, phys, rev, on, values, res, extra, NOTES[kind])
                    summary["sessions"] += 1
                summary["beams"].append(label)
        for modality, spec in RESERVE:
            self.ensure_calibrations(modality, spec)
        self.c.execute("INSERT INTO audit_log(action, entity, details) VALUES ('seed_demo', 'seed', %s)",
                       (Jsonb({**self.created, "sessions": summary["sessions"]}),))
        return summary


def default_end(today: dt.date) -> dt.date:
    """Month of the last record: the latest month whose 15th (the measurement day) is not in the future."""
    return today.replace(day=1) if today.day >= 15 else month_start(today, 1)


def seed(conn, months: int = 24, end: dt.date | None = None):
    end = end or default_end(dt.date.today())
    return Seeder(conn).run(months, end)


def remove(conn):
    """Delete the demo measurements and whatever the seeding created (never the user's own equipment or data)."""
    ids = {k: set() for k in ("beams", "calibrations", "units", "electrometers", "users", "linacs", "linac_fields", "beam_fields")}
    for row in conn.execute("SELECT details FROM audit_log WHERE action = 'seed_demo' ORDER BY id").fetchall():
        for k in ids:
            ids[k].update(row["details"].get(k, []))
    sess = [r["id"] for r in conn.execute("SELECT id FROM measurement_sessions WHERE extra->>'demo' = 'true'").fetchall()]
    # a record of the user that replaces a demo record stays; it just loses the link to the removed original
    conn.execute("UPDATE measurement_sessions SET supersedes_id = NULL WHERE supersedes_id = ANY(%s) OR id = ANY(%s)", (sess, sess))
    conn.execute("DELETE FROM results WHERE session_id = ANY(%s)", (sess,))
    conn.execute("DELETE FROM measurement_sessions WHERE id = ANY(%s)", (sess,))
    unused = {
        "calibrations": "DELETE FROM calibrations c WHERE c.id = ANY(%s) AND NOT EXISTS "
                        "(SELECT 1 FROM measurement_sessions s WHERE s.calibration_id = c.id)",
        "units": "DELETE FROM chamber_units u WHERE u.id = ANY(%s) AND NOT EXISTS "
                 "(SELECT 1 FROM calibrations c WHERE c.chamber_unit_id = u.id)",
        "electrometers": "DELETE FROM electrometers e WHERE e.id = ANY(%s) AND NOT EXISTS "
                         "(SELECT 1 FROM calibrations c WHERE c.electrometer_id = e.id)",
    }
    for key, sql in unused.items():
        conn.execute(sql, (list(ids[key]),))
    conn.execute("DELETE FROM spc_baseline WHERE beam_id = ANY(%s)", (list(ids["beams"]),))
    conn.execute("""DELETE FROM beams b WHERE b.id = ANY(%s) AND NOT EXISTS (SELECT 1 FROM measurement_sessions s WHERE s.beam_id = b.id)
                    AND NOT EXISTS (SELECT 1 FROM legacy_journal j WHERE j.beam_id = b.id)""", (list(ids["beams"]),))
    conn.execute("UPDATE linacs SET model = NULL, serial_no = NULL WHERE id = ANY(%s)", (list(ids["linac_fields"]),))
    conn.execute("""UPDATE beams SET dose_rate_mu = NULL, field_size = NULL, phantom = NULL, c_pl = NULL, h_pl = NULL,
                    zmax = NULL WHERE id = ANY(%s)""", (list(ids["beam_fields"]),))
    conn.execute("""DELETE FROM linacs l WHERE l.id = ANY(%s) AND NOT EXISTS (SELECT 1 FROM beams b WHERE b.linac_id = l.id)""",
                 (list(ids["linacs"]),))
    conn.execute("""DELETE FROM users u WHERE u.login IN ('demo_phys', 'demo_rev') AND NOT EXISTS
                    (SELECT 1 FROM measurement_sessions s WHERE s.created_by = u.id OR s.approved_by = u.id)""")
    conn.execute("INSERT INTO audit_log(action, entity, details) VALUES ('remove_demo', 'seed', %s)",
                 (Jsonb({"sessions_removed": len(sess)}),))
    return len(sess)


def database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = {}
    path = Path(__file__).resolve().parent.parent / ".env"
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return f"postgresql://trs_owner:{env['TRS_OWNER_PASSWORD']}@127.0.0.1:5433/trs398"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remove", action="store_true", help="remove the demo data this script added")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--end", type=dt.date.fromisoformat, default=None, help="month of the last record (default: the latest month already past its 15th)")
    a = ap.parse_args()
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        services.seed_chambers(conn)
        if a.remove:
            print(f"removed {remove(conn)} demo measurements")
        else:
            s = seed(conn, a.months, a.end)
            print(f"added {s['sessions']} measurements on {len(s['beams'])} beams")
            for line in s["skipped"]:
                print("skipped (has real data):", line)
        conn.commit()


if __name__ == "__main__":
    main()
