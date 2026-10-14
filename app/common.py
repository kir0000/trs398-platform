"""Helpers that several parts of the web side use: names of beams and series, the points of a trend, the reminder about the calibration."""
from datetime import date, timedelta

from core import spc


def beam_label(b):
    unit = "MV" if b["modality"] == "photon" else "MeV"
    return f"{b['linac']}, {b['nominal_energy']:g} {unit}{' FFF' if b['fff'] else ''}"


def key_label(key):
    """The series of a trend in words."""
    if key == "SSD":
        return "SSD: доза на z_max на 1 MU, норма 1 сГр/MU"
    if key == "SAD|old":
        return "SAD: доза на z_max через TMR (без ожидаемой дозы)"
    parts = key.split("|")
    if len(parts) == 4 and parts[0] == "SAD":
        z = parts[1].removeprefix("z=")
        return (f"SAD: опорная точка на глубине {z.replace('.', ',')} г/см², поле {parts[2] or 'не указано'}, "
                f"ожидаемая доза {parts[3].replace('.', ',')} сГр/MU (система планирования)")
    return key


REFERENCE_FIELDS = ("m1_v1", "m_plus", "m_minus", "m2", "v1", "v2", "pulsed_scanned")


# what "make these values the reference of the beam" stores: the quality inputs (section 1), the series M and MU (section 3),
# polarity (iii) and recombination (iv)
REFERENCE_SAVED = REFERENCE_FIELDS + ("tpr", "pdd10", "pdd20", "r50", "mu", "m1")


# ---------------------------------------------------------------- trends
def trend_keys(conn, beam):
    """The series of a beam: [(ref_key, records, last date)], the one with the latest record first. SSD and SAD records with
    different reference conditions are different series."""
    return conn.execute("""SELECT ref_key, count(*) AS n, max(measured_on) AS last_on FROM v_trend
        WHERE linac = %s AND modality = %s AND nominal_energy = %s AND fff = %s GROUP BY ref_key ORDER BY max(measured_on) DESC, ref_key""",
                        (beam["linac"], beam["modality"], beam["nominal_energy"], beam["fff"])).fetchall()


def trend_points(conn, beam, key=None):
    """Points of one series: `key`, else the series of the record itself (a session row carries ref_key), else the latest one."""
    key = key or beam.get("ref_key") or next((k["ref_key"] for k in trend_keys(conn, beam)[:1]), None)
    rows = conn.execute("""SELECT measured_on, deviation_pct, source FROM v_trend
        WHERE linac = %s AND modality = %s AND nominal_energy = %s AND fff = %s AND ref_key IS NOT DISTINCT FROM %s
        ORDER BY measured_on, source, record_id""",
                        (beam["linac"], beam["modality"], beam["nominal_energy"], beam["fff"], key)).fetchall()
    return [spc.Point(r["measured_on"], float(r["deviation_pct"])) for r in rows]


def beam_periods(conn, beam_id):
    """Baseline periods of a beam: [(from, to)] and the rows for the page."""
    rows = conn.execute("""SELECT bl.*, u.full_name AS who FROM spc_baseline bl LEFT JOIN users u ON u.id = bl.set_by
                           WHERE bl.beam_id = %s ORDER BY bl.from_date""", (beam_id,)).fetchall()
    return [(r["from_date"], r["to_date"]) for r in rows], rows


def unc_settings(conn, modality):
    """(overrides {code: u}, extras [..]) of the Type B uncertainty budget of a modality, as edited by the users."""
    rows = conn.execute("SELECT * FROM uncertainty_settings WHERE modality = %s AND active ORDER BY id", (modality,)).fetchall()
    overrides = {r["code"]: float(r["u_pct"]) for r in rows if not r["is_extra"]}
    extras = [dict(code=r["code"], name=r["name"], stage=r["stage"], u_pct=float(r["u_pct"]), note=r["note"],
                   dist=r["dist"] or "", how=r["how"] or "")
              for r in rows if r["is_extra"]]
    return overrides, extras


REMINDER_MONTHS = 3                                  # a chamber calibration is reminded about this many months before it expires


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    year, month = d.year + m // 12, m % 12 + 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def calibration_state(c, today) -> dict:
    """Validity of a calibration: expired, soon (within the reminder period of 3 calendar months) or valid."""
    if not c.get("valid_until"):
        return {"state": "none", "days": None}
    days = (c["valid_until"] - today).days
    return {"state": "expired" if days < 0 else "soon" if c["valid_until"] <= add_months(today, REMINDER_MONTHS) else "ok", "days": days}


def calibration_reminders(conn, today) -> list[dict]:
    """The chambers whose newest calibration has expired or expires within 3 months (the banner on the list of measurements)."""
    rows = conn.execute("""SELECT ch.name AS chamber, cu.serial_no, cal.valid_until, cal.calibrated_on
        FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id JOIN chambers ch ON ch.id = cu.chamber_id
        ORDER BY ch.name, cu.serial_no, cal.calibrated_on DESC, cal.id DESC""").fetchall()
    newest = {}
    for r in rows:
        newest.setdefault((r["chamber"], r["serial_no"]), r)         # the first row of a unit is its newest calibration
    out = []
    for r in newest.values():
        st = calibration_state(r, today)
        if st["state"] in ("expired", "soon"):
            out.append({**r, **st})
    return sorted(out, key=lambda r: r["valid_until"])
