"""tools/seed_demo.py against a throw-away database: what it adds, what it must not touch, and that it can be undone."""
import datetime as dt
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import seed_demo  # noqa: E402
from app import services  # noqa: E402

DB = "trs398_seed_test"
END = dt.date(2026, 9, 1)


def read_env():
    env = {k: os.environ[k] for k in ("TRS_OWNER_PASSWORD",) if k in os.environ}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


@pytest.fixture()
def conn(tmp_path):
    from app import db as appdb
    c = appdb.connect(tmp_path / "seed_test.db")
    appdb.migrate(c)
    services.seed_chambers(c)
    # the user's own equipment: a linac with real imported history on its 6 MV FFF beam, and an empty one
    c.execute("INSERT INTO linacs(name) VALUES ('TrueBeam'), ('Versa HD')")
    lid = c.execute("SELECT id FROM linacs WHERE name='TrueBeam'").fetchone()["id"]
    bid = c.execute("INSERT INTO beams(linac_id, modality, nominal_energy, fff) VALUES (%s,'photon',6,1) RETURNING id",
                    (lid,)).fetchone()["id"]
    for i in range(5):
        c.execute("INSERT INTO legacy_journal(beam_id, measured_on, deviation_pct, dw_zmax, source_file) "
                  "VALUES (%s,%s,0.1,%s,'real')", (bid, f"2024-0{i + 1}-01", 0.01 + i / 1e6))
    c.commit()
    yield c
    c.close()


def one(c, sql, *a):
    return c.execute(sql, a).fetchone()


def test_seed_fills_equipment_and_data_like_the_templates(conn):
    s = seed_demo.seed(conn, 24, END)
    conn.commit()
    assert s["skipped"] == ["TrueBeam: photon 6 FFF"]                         # real history is never touched
    beams = 7 + 8 - 1
    assert len(s["beams"]) == beams and s["sessions"] == beams * 24

    # several linacs and several energies, with model and serial number
    assert one(conn, "SELECT model, serial_no FROM linacs WHERE name='Versa HD'") == {"model": "Elekta Versa HD",
                                                                                      "serial_no": "7213"}
    assert one(conn, "SELECT count(DISTINCT nominal_energy) AS n FROM beams WHERE modality='electron'")["n"] == 4
    assert one(conn, "SELECT count(DISTINCT nominal_energy) AS n FROM beams WHERE modality='photon'")["n"] >= 3

    # the current calibrations carry the templates' values: SNC600c Farmer 0.05138, PTW 34001 Roos 0.5791
    cur = {r["name"]: (float(r["nd_w"]), r["serial_no"]) for r in conn.execute("""
        SELECT ch.name, cal.nd_w, cu.serial_no FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
        JOIN chambers ch ON ch.id = cu.chamber_id WHERE cal.calibrated_on = '2026-02-01'""").fetchall()}
    assert cur == {"Sun Nuclear SNC600c Farmer": (0.05138, "123456789"), "PTW 34001 Roos": (0.5791, "123456789")}

    # equipment parameters of worksheet sections 1-3 are filled in, so the sheet can show them
    beam = one(conn, """SELECT b.dose_rate_mu, b.field_size, b.phantom, b.c_pl, b.zmax FROM beams b JOIN linacs l ON l.id = b.linac_id
                        WHERE l.name = 'Versa HD' AND b.modality = 'photon' AND b.nominal_energy = 6 AND NOT b.fff""")
    assert (float(beam["dose_rate_mu"]), beam["field_size"], beam["phantom"], float(beam["c_pl"]), float(beam["zmax"])) == (600.0, "10 х 10", "водный", 1.0, 1.5)
    cal = one(conn, """SELECT cal.*, ch.name FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
                       JOIN chambers ch ON ch.id = cu.chamber_id WHERE cal.calibrated_on = '2026-02-01' AND ch.name = 'Sun Nuclear SNC600c Farmer'""")
    assert (cal["polarity_cal"], cal["polarity_user"], cal["kelec_separate"], cal["kelec_lab"]) == ("−", "−", True, "ВНИИФТРИ")
    assert (float(cal["voltage_v"]), float(cal["t0"]), float(cal["p0"]), float(cal["cal_depth"]), cal["el_range"]) == (-300.0, 22.0, 101.325, 5.0, "Medium")
    ecal = one(conn, """SELECT cal.* FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
                        JOIN chambers ch ON ch.id = cu.chamber_id WHERE cal.calibrated_on = '2026-02-01' AND ch.name = 'PTW 34001 Roos'""")
    assert (ecal["polarity_cal"], float(ecal["voltage_v"]), float(ecal["t0"]), ecal["kelec_separate"]) == ("+", 300.0, 20.0, False)

    # every record is approved by a different person, has a result, and uses the calibration valid on its date
    bad = one(conn, "SELECT count(*) AS n FROM measurement_sessions WHERE status <> 'approved' "
                    "OR approved_by = created_by")["n"]
    assert bad == 0
    assert one(conn, "SELECT count(*) AS n FROM measurement_sessions s LEFT JOIN results r ON r.session_id = s.id "
                     "WHERE r.session_id IS NULL")["n"] == 0
    assert one(conn, """SELECT count(*) AS n FROM measurement_sessions s JOIN calibrations c ON c.id = s.calibration_id
                        WHERE c.calibrated_on > s.measured_on OR c.valid_until < s.measured_on""")["n"] == 0
    users = {r["login"]: r["is_active"] for r in conn.execute("SELECT login, is_active FROM users").fetchall()}
    assert users == {"demo_phys": False, "demo_rev": False}                    # nobody can log in as them
    dates = one(conn, "SELECT min(measured_on) AS a_on, max(measured_on) AS b_on FROM measurement_sessions")
    assert (dates["a_on"], dates["b_on"]) == (dt.date(2024, 10, 15), dt.date(2026, 9, 15))


def test_the_series_look_like_real_output_data(conn):
    seed_demo.seed(conn, 24, END)
    conn.commit()
    devs = [float(r["deviation_pct"]) for r in conn.execute("SELECT deviation_pct FROM results").fetchall()]
    assert len(devs) == 14 * 24
    mean = sum(devs) / len(devs)
    assert abs(mean) < 0.8 and max(abs(d) for d in devs) < 4                    # plausible scale
    assert sum(1 for d in devs if abs(d) > 1.0) >= 3                            # some beams show an excursion to detect
    assert sum(1 for d in devs if abs(d) <= 1.0) > 0.85 * len(devs)             # but most points are in control
    assert max(abs(d) for d in devs) > 2.0                                      # one clear out-of-tolerance excursion
    # the fixed scenarios: Versa HD 6 MV jumps out of tolerance and is re-adjusted; TrueBeam 12 MeV drifts upwards
    def series(linac, modality, energy):
        return [float(r["deviation_pct"]) for r in conn.execute("""SELECT r.deviation_pct FROM results r
            JOIN measurement_sessions s ON s.id = r.session_id JOIN beams b ON b.id = s.beam_id JOIN linacs l ON l.id = b.linac_id
            WHERE l.name = %s AND b.modality = %s AND b.nominal_energy = %s AND NOT b.fff ORDER BY s.measured_on""",
                                                                   (linac, modality, energy)).fetchall()]
    jump = series("Versa HD", "photon", 6)
    assert jump[14] > 2.0 and abs(jump[15]) < 1.0 and abs(jump[20]) < 1.0       # event in month 15, adjusted right after
    drift = series("TrueBeam", "electron", 12)
    assert sum(drift[-6:]) / 6 - sum(drift[:6]) / 6 > 0.7 and max(abs(x) for x in drift) < 2.0
    # stored results are the core's results for the stored raw readings (recompute one photon record)
    from core import photon as ph
    r = one(conn, """SELECT s.*, r.dw_zmax, b.fff, cal.nd_w, cal.k_elec FROM measurement_sessions s
        JOIN results r ON r.session_id = s.id JOIN beams b ON b.id = s.beam_id
        JOIN calibrations cal ON cal.id = s.calibration_id WHERE b.modality = 'photon' ORDER BY s.id LIMIT 1""")
    f = lambda xs: [float(x) for x in xs]
    again = ph.calculate(ph.PhotonInput(
        chamber_id=26, nd_w=float(r["nd_w"]), mu=float(r["mu"]), pressure_kpa=float(r["pressure_kpa"]),
        temp_c=float(r["temp_c"]), v1=float(r["v1"]), v2=float(r["v2"]), m1=f(r["m1_readings"]), m2=f(r["m2_readings"]),
        m_plus=f(r["m_plus_readings"]), m_minus=f(r["m_minus_readings"]), tpr=float(r["beam_quality"]), fff=r["fff"],
        pdd_zref=float(r["pdd_zref"]), k_elec=float(r["k_elec"])))
    assert again.dw_zmax == pytest.approx(float(r["dw_zmax"]), rel=1e-9)


def test_seeding_twice_adds_nothing(conn):
    seed_demo.seed(conn, 24, END)
    conn.commit()
    n = one(conn, "SELECT count(*) AS n FROM measurement_sessions")["n"]
    again = seed_demo.seed(conn, 24, END)
    conn.commit()
    assert again["sessions"] == 0 and one(conn, "SELECT count(*) AS n FROM measurement_sessions")["n"] == n


def test_remove_deletes_only_what_the_seed_added(conn):
    tables = ("linacs", "beams", "legacy_journal", "calibrations", "users")
    before = {t: one(conn, f"SELECT count(*) AS n FROM {t}")["n"] for t in tables}
    seed_demo.seed(conn, 24, END)
    conn.commit()
    removed = seed_demo.remove(conn)
    conn.commit()
    assert removed == 14 * 24
    after = {t: one(conn, f"SELECT count(*) AS n FROM {t}")["n"] for t in tables}
    assert after == before                                                      # equipment and real data exactly as before
    assert one(conn, "SELECT count(*) AS n FROM measurement_sessions")["n"] == 0
    assert one(conn, "SELECT count(*) AS n FROM results")["n"] == 0
    assert one(conn, "SELECT count(*) AS n FROM electrometers")["n"] == 0
    assert one(conn, "SELECT model, serial_no FROM linacs WHERE name='Versa HD'") == {"model": None, "serial_no": None}
    assert one(conn, "SELECT count(*) AS n FROM beams WHERE dose_rate_mu IS NOT NULL OR field_size IS NOT NULL")["n"] == 0
    assert one(conn, "SELECT count(*) AS n FROM legacy_journal WHERE NOT is_demo")["n"] == 5       # the real history survives
    assert one(conn, "SELECT count(*) AS n FROM audit_log WHERE action IN ('seed_demo','remove_demo')")["n"] == 2


def test_real_measurements_survive_removal(conn):
    seed_demo.seed(conn, 24, END)
    beam = one(conn, "SELECT id FROM beams WHERE modality='electron' AND nominal_energy=6 LIMIT 1")["id"]
    cal = one(conn, "SELECT id FROM calibrations LIMIT 1")["id"]
    phys = one(conn, "SELECT id FROM users WHERE login='demo_phys'")["id"]
    conn.execute("INSERT INTO users(login, full_name, role, password_hash) VALUES ('real', 'Реальный', 'reviewer', 'x')")
    rev = one(conn, "SELECT id FROM users WHERE login='real'")["id"]
    conn.execute("""INSERT INTO measurement_sessions(measured_on, beam_id, calibration_id, geometry, mu, pressure_kpa, temp_c,
        v1, v2, m1_readings, m2_readings, beam_quality, created_by, approved_by, status, approved_at)
        VALUES ('2026-09-30', %s, %s, 'SSD', 100, 101, 22, 300, 100, '{1}', '{1}', 2.4, %s, %s, 'approved', now())""",
                 (beam, cal, phys, rev))
    conn.commit()
    seed_demo.remove(conn)
    conn.commit()
    assert one(conn, "SELECT count(*) AS n FROM measurement_sessions")["n"] == 1        # the non-demo record stays
    assert one(conn, "SELECT count(*) AS n FROM beams WHERE id = %s", beam)["n"] == 1    # ... and so does its beam


def test_default_end_never_lies_in_the_future(conn):
    assert seed_demo.default_end(dt.date(2026, 10, 12)) == dt.date(2026, 9, 1)     # the 15th of October has not come yet
    assert seed_demo.default_end(dt.date(2026, 10, 15)) == dt.date(2026, 10, 1)
    assert seed_demo.default_end(dt.date(2026, 1, 3)) == dt.date(2025, 12, 1)
    seed_demo.seed(conn, 3)                                                         # default end
    conn.commit()
    assert one(conn, "SELECT max(measured_on) AS d_on FROM measurement_sessions")["d_on"] <= dt.date.today()


def test_seeded_records_fill_the_edit_form_from_their_columns(conn):
    """The record shape the seeder writes (data in columns, a few extras) must be enough for the entry form."""
    seed_demo.seed(conn, 2, END)
    conn.commit()
    row = one(conn, """SELECT s.*, b.modality FROM measurement_sessions s JOIN beams b ON b.id = s.beam_id
                       WHERE b.modality = 'electron' LIMIT 1""")
    assert row["extra"]["form"].get("mu") is None and row["m1_readings"] and row["pressure_kpa"] is not None


def test_a_users_replacement_draft_survives_removal_and_does_not_block_reseeding(conn):
    """The user clicked "Supersede" («Заменить») on a demo record and submitted the copy; the seeder must neither break nor touch it."""
    seed_demo.seed(conn, 3, END)
    row = one(conn, """SELECT s.id, s.beam_id, s.calibration_id FROM measurement_sessions s JOIN beams b ON b.id = s.beam_id
                       WHERE b.modality = 'electron' AND b.nominal_energy = 6 ORDER BY s.id LIMIT 1""")
    conn.execute("INSERT INTO users(login, full_name, role, password_hash) VALUES ('real', 'Реальный', 'physicist', 'x')")
    real = one(conn, "SELECT id FROM users WHERE login='real'")["id"]
    draft = conn.execute("""INSERT INTO measurement_sessions(measured_on, beam_id, calibration_id, geometry, mu, pressure_kpa, temp_c,
        v1, v2, m1_readings, m2_readings, beam_quality, created_by, status, supersedes_id, supersede_reason, extra)
        VALUES ('2026-09-15', %s, %s, 'SSD', 100, 101, 22, 300, 100, '{1}', '{1}', 2.4, %s, 'submitted', %s, 'тест', '{}')
        RETURNING id""", (row["beam_id"], row["calibration_id"], real, row["id"])).fetchone()["id"]
    conn.commit()
    seed_demo.remove(conn)                                                        # used to raise a foreign key violation
    conn.commit()
    left = one(conn, "SELECT status, supersedes_id, supersede_reason FROM measurement_sessions WHERE id = %s", draft)
    assert left == {"status": "submitted", "supersedes_id": None, "supersede_reason": "тест"}
    assert one(conn, "SELECT count(*) AS n FROM measurement_sessions")["n"] == 1
    # the draft does not count as real history: its beam is seeded again, and the kept calibration is brought up to date
    conn.execute("UPDATE calibrations SET polarity_cal = NULL, cal_depth = NULL WHERE id = %s", (row["calibration_id"],))
    conn.commit()
    again = seed_demo.seed(conn, 3, END)
    conn.commit()
    assert "Versa HD: electron 6" in " ".join(again["beams"]) or any("electron 6" in b for b in again["beams"])
    assert one(conn, "SELECT count(*) AS n FROM measurement_sessions WHERE json_extract(extra, '$.demo') IN (1, 'true')")["n"] > 0
    cal = one(conn, "SELECT polarity_cal, cal_depth FROM calibrations WHERE id = %s", row["calibration_id"])
    assert cal["polarity_cal"] is not None and float(cal["cal_depth"]) == 5.0


def test_a_common_cause_is_visible_to_the_comparison(conn):
    """TrueBeam: every energy shifts together for two months, so the comparison must flag them as a common shift."""
    from core import compare, spc
    seed_demo.seed(conn, 24, END)
    conn.commit()
    series = {}
    for r in conn.execute("""SELECT b.modality, b.nominal_energy, b.fff, s.measured_on, r.deviation_pct FROM measurement_sessions s
        JOIN results r ON r.session_id = s.id JOIN beams b ON b.id = s.beam_id JOIN linacs l ON l.id = b.linac_id
        WHERE l.name = 'TrueBeam' ORDER BY s.measured_on""").fetchall():
        series.setdefault((r["modality"], float(r["nominal_energy"]), r["fff"]), []).append(spc.Point(r["measured_on"], float(r["deviation_pct"])))
    months, matrix = compare.align({str(k): v for k, v in series.items()})
    flagged = {c.month: c for c in compare.common_mode(months, matrix) if c.flagged}
    assert {"2026-03", "2026-04"} <= set(flagged) and flagged["2026-03"].direction == "вверх" and flagged["2026-03"].n == 6
    # Versa HD has no common event: its months are not flagged in those months
    versa = {}
    for r in conn.execute("""SELECT b.modality, b.nominal_energy, b.fff, s.measured_on, r.deviation_pct FROM measurement_sessions s
        JOIN results r ON r.session_id = s.id JOIN beams b ON b.id = s.beam_id JOIN linacs l ON l.id = b.linac_id
        WHERE l.name = 'Versa HD' ORDER BY s.measured_on""").fetchall():
        versa.setdefault((r["modality"], float(r["nominal_energy"]), r["fff"]), []).append(spc.Point(r["measured_on"], float(r["deviation_pct"])))
    vm, vmat = compare.align({str(k): v for k, v in versa.items()})
    assert "2026-03" not in {c.month for c in compare.common_mode(vm, vmat) if c.flagged}


def deviations_by_beam(conn):
    out = {}
    for r in conn.execute("""SELECT l.name AS linac, b.modality, b.nominal_energy AS e, b.fff, s.measured_on, r.deviation_pct AS d
                             FROM measurement_sessions s JOIN results r ON r.session_id = s.id JOIN beams b ON b.id = s.beam_id
                             JOIN linacs l ON l.id = b.linac_id ORDER BY s.measured_on""").fetchall():
        out.setdefault((r["linac"], r["modality"], r["e"], bool(r["fff"])), []).append(float(r["d"]))
    return out


def corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5


def test_three_years_with_dependencies_between_the_energies(conn):
    s = seed_demo.seed(conn, 36, END, linked=True)
    beams = 14                                                                   # two linacs, 15 beams, one has real history
    assert s["sessions"] == beams * 36
    dates = one(conn, "SELECT min(measured_on) AS a_on, max(measured_on) AS b_on FROM measurement_sessions")
    assert (dates["a_on"], dates["b_on"]) == (dt.date(2023, 10, 15), dt.date(2026, 9, 15))
    # every record has a calibration that was valid on its day (the series starts before the first calibration of the set)
    assert one(conn, """SELECT count(*) AS n FROM measurement_sessions s JOIN calibrations c ON c.id = s.calibration_id
                        WHERE c.calibrated_on > s.measured_on OR c.valid_until < s.measured_on""")["n"] == 0
    dev = deviations_by_beam(conn)
    assert all(len(v) == 36 for v in dev.values())
    # the energies of one linac move together, the linacs do not move with each other
    tb = [dev[("TrueBeam", "electron", e, False)] for e in (6, 9, 12, 15)]
    same = [corr(a, b) for i, a in enumerate(tb) for b in tb[i + 1:]]
    other = [corr(a, dev[("Versa HD", "electron", 9, False)]) for a in tb]
    assert sum(same) / len(same) > sum(other) / len(other) + 0.15
    # group events: TrueBeam photons together in months 9-11, all electrons of Versa HD from 9 MeV in months 18-19, 6 MeV not
    photons = [v for k, v in dev.items() if k[:2] == ("TrueBeam", "photon")]
    base = sum(sum(v[3:7]) / 4 for v in photons) / len(photons)
    event = sum(sum(v[8:10]) / 2 for v in photons) / len(photons)
    assert event - base > 0.3
    v9, v6 = dev[("Versa HD", "electron", 9, False)], dev[("Versa HD", "electron", 6, False)]
    shift9 = sum(v9[17:19]) / 2 - sum(v9[12:16]) / 4
    shift6 = sum(v6[17:19]) / 2 - sum(v6[12:16]) / 4
    assert shift9 > 0.3 and shift9 > shift6 + 0.2
