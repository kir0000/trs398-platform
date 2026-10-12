"""Glue between web forms, the calculation core and the database."""
from __future__ import annotations

import re
from dataclasses import asdict

from core import electron as el
from core import photon as ph


class InputError(ValueError):
    """User-facing validation error (message is shown in the form)."""


def num(text, name, required=True, lo=None, hi=None):
    s = (text or "").strip().replace(",", ".")
    if not s:
        if required:
            raise InputError(f"Заполните поле «{name}»")
        return None
    try:
        v = float(s)
    except ValueError:
        raise InputError(f"«{name}»: не число ({text})") from None
    if lo is not None and v < lo or hi is not None and v > hi:
        raise InputError(f"«{name}»: значение {v:g} вне допустимого диапазона {lo}–{hi}")
    return v


def readings(text, name, required=True):
    parts = [p for p in re.split(r"[\s;/]+", (text or "").strip()) if p]
    if not parts:
        if required:
            raise InputError(f"Введите показания «{name}»")
        return None
    return [num(p, name) for p in parts]


def chamber_names() -> dict[str, list[str]]:
    return {
        "photon": [c["name"] for c in ph.load_tables()["chambers"]],
        "electron": [c["name"] for c in el.load_tables()["chambers"]],
    }


def seed_chambers(conn):
    version = ph.load_tables()["tables_version"]
    names = dict.fromkeys(chamber_names()["photon"] + chamber_names()["electron"])
    for n in names:
        conn.execute("INSERT INTO chambers(name, table_version) VALUES (%s, %s) ON CONFLICT DO NOTHING", (n, version))


def core_chamber_id(modality: str, name: str) -> int:
    tables = ph.load_tables() if modality == "photon" else el.load_tables()
    for c in tables["chambers"]:
        if c["name"] == name:
            return c["id"]
    raise InputError(f"Камера «{name}» не входит в таблицы kQ для этого типа пучка")


FARMER_ND_W = (0.035, 0.075)        # Gy/nC, typical for cylindrical chambers of about 0.6 cm3
PLANE_PARALLEL_ND_W = (0.3, 2.0)    # Gy/nC, Roos, NACP, Markus types


def nd_w_warning(chamber_name: str, nd_w) -> str | None:
    """A soft hint (never a block) when ND,w does not look like the chamber type: a typo or a wrong unit.

    Only chamber classes with a well-known range are judged (Farmer type and plane-parallel); small chambers vary too much.
    """
    try:
        value = float(nd_w)
    except (TypeError, ValueError):
        return None
    lo_hi = None
    for c in ph.load_tables()["chambers"]:
        if c["name"] == chamber_name and (c.get("cavity_length_cm") or 0) >= 1.9:
            lo_hi = FARMER_ND_W
    for c in el.load_tables()["chambers"]:
        if c["name"] == chamber_name:
            lo_hi = PLANE_PARALLEL_ND_W if c.get("plane_parallel") else FARMER_ND_W
    if lo_hi and not lo_hi[0] <= value <= lo_hi[1]:
        fmt = lambda x: f"{x:g}".replace(".", ",")
        return (f"ND,w = {fmt(value)} Гр/нКл вне типичного диапазона {fmt(lo_hi[0])}–{fmt(lo_hi[1])} для камер этого типа: "
                "проверьте значение и единицы по сертификату")
    return None


def effective_kelec(calib) -> float:
    """kelec of the electrometer: the certificate value (e.g. from VNIIFTRI) only if it was calibrated separately from
    the chamber, otherwise 1 (TRS-398 Rev.1, worksheet note c)."""
    return float(calib["k_elec"]) if calib.get("kelec_separate") else 1.0


def user_polarity_series(f: dict) -> str | None:
    """Text of the series M at the user's polarity for kpol: M+ or M-, as set by the user's polarity in Equipment.

    An explicit `m_user` wins. With both signs, or none, there is no derived series and the calculation falls back to
    the readings of section 3 (V1, user polarity).

    Used when a record is entered (see `with_user_series`); the calculation itself only reads `m_user`, so a stored
    record always reproduces from the snapshot it was saved with.
    """
    if f.get("m_user"):
        return f["m_user"]
    pol = (f.get("polarity_user") or "").replace("-", "−").strip()
    if pol == "+" and f.get("m_plus"):
        return f["m_plus"]
    if pol == "−" and f.get("m_minus"):
        return f["m_minus"]
    return None


def with_user_series(f: dict) -> dict:
    """The form values plus `m_user` set from the user's polarity (so that it is stored with the record)."""
    series = user_polarity_series(f)
    return {**f, "m_user": series} if series else dict(f)


DRIFT_OK, DRIFT_WARN = 0.2, 0.5          # % of the mean over the whole series


def series_stats(vals) -> dict | None:
    """Mean, drift and scatter of a series of readings (needs three or more).

    drift: least-squares trend over the series as a percentage of the mean (positive: readings grow);
    scatter: standard deviation as a percentage of the mean. Status by |drift|: ok / warn / err.
    """
    vals = [float(v) for v in vals]
    n = len(vals)
    if n < 3:
        return None
    mean = sum(vals) / n
    if not mean:
        return None
    xm = (n - 1) / 2
    sxx = sum((i - xm) ** 2 for i in range(n))
    slope = sum((i - xm) * (v - mean) for i, v in enumerate(vals)) / sxx
    drift = slope * (n - 1) / mean * 100
    sd = (sum((v - mean) ** 2 for v in vals) / (n - 1)) ** 0.5 / abs(mean) * 100
    status = "ok" if abs(drift) <= DRIFT_OK else "warn" if abs(drift) <= DRIFT_WARN else "err"
    return {"mean": mean, "drift_pct": drift, "sd_pct": sd, "n": n, "status": status}


def compute(modality: str, f: dict, beam: dict, calib: dict, chamber_name: str):
    """Validate the form dict `f`, run the calculation, return (quality, results dict, extra)."""
    cid = core_chamber_id(modality, chamber_name)
    mu = num(f.get("mu"), "MU", lo=1, hi=100000)
    p = num(f.get("pressure"), "P, кПа", lo=80, hi=110)
    t = num(f.get("temp"), "T, °C", lo=10, hi=35)
    v1 = num(f.get("v1"), "V1, В")
    v2 = num(f.get("v2"), "V2, В")
    if not v1 or not v2 or abs(v1) <= abs(v2):
        raise InputError("V1 должно быть по модулю больше V2 (метод двух напряжений)")
    m1 = readings(f.get("m1"), "M1")
    m2 = readings(f.get("m2"), "M2")
    m_plus = readings(f.get("m_plus"), "M+", required=False)
    m_minus = readings(f.get("m_minus"), "M−", required=False)
    if bool(m_plus) != bool(m_minus):
        raise InputError("Для поправки на полярность введите и M+, и M−")
    m_user = readings(f.get("m_user"), "M (полярность пользователя)", required=False)    # (iii) set from M+/M- when the record is entered
    m1_ks = readings(f.get("m1_v1"), "M1 при V1", required=False)                          # (iv) series of the reference determination
    k_elec = effective_kelec(calib)
    pulsed_scanned = bool(f.get("pulsed_scanned"))
    k_pol_q0 = num(f.get("k_pol_q0"), "kpol(Q0)", required=False, lo=0.9, hi=1.1) or 1.0
    t0 = num(f.get("t0"), "T0, °C", required=False, lo=0, hi=40)
    p0 = num(f.get("p0"), "P0, кПа", required=False, lo=80, hi=110)

    try:
        if modality == "photon":
            geometry = f.get("geometry", "SSD")
            tpr = num(f.get("tpr"), "TPR20,10", required=False, lo=0.3, hi=0.95)
            if tpr is None:
                pdd10 = num(f.get("pdd10"), "PDD(10), %", lo=30, hi=100)
                pdd20 = num(f.get("pdd20"), "PDD(20), %", required=not beam["fff"], lo=10, hi=100)
                tpr = ph.beam_quality_tpr(beam["fff"], pdd10, pdd20)
            pdd = num(f.get("pdd_zref"), "PDD(zref), %", required=geometry == "SSD", lo=30, hi=100)
            expected = num(f.get("exp_cgy_mu"), "ожидаемая доза в опорной точке", required=False, lo=0.2, hi=3) if geometry == "SAD" else None
            tmr = num(f.get("tmr_zref"), "TMR(zref)", required=geometry == "SAD" and expected is None, lo=0.3, hi=1.2)
            kwargs = dict(chamber_id=cid, nd_w=float(calib["nd_w"]), mu=mu, pressure_kpa=p, temp_c=t, v1=v1, v2=v2,
                          m1=m1, m2=m2, tpr=tpr, fff=beam["fff"], pdd_zref=pdd, tmr_zref=tmr, expected_cgy_mu=expected, m_plus=m_plus,
                          m_minus=m_minus, k_elec=k_elec, k_pol_q0=k_pol_q0, m_pol=m_user, m1_ks=m1_ks,
                          pulsed_scanned=pulsed_scanned, geometry=geometry,
                          zref=num(f.get("zref"), "zref", required=False, lo=1, hi=20) or 10.0,
                          ref_distance_cm=num(f.get("ref_distance"), "SSD, см", required=False, lo=50, hi=200) or 100.0)
            if t0 is not None:
                kwargs["t0_c"] = t0
            if p0 is not None:
                kwargs["p0_kpa"] = p0
            r = ph.calculate(ph.PhotonInput(**kwargs))
            quality, k_vol = tpr, r.k_vol
        else:
            r50 = num(f.get("r50"), "R50 измеренное, г/см²", lo=0.5, hi=12)
            pdd = num(f.get("pdd_zref"), "PDD(zref), %", lo=30, hi=100)
            q0_co60 = bool(f.get("q0_is_co60"))
            kwargs = dict(chamber_id=cid, nd_w=float(calib["nd_w"]), mu=mu, pressure_kpa=p, temp_c=t, v1=v1, v2=v2,
                          m1=m1, m2=m2, r50_measured=r50, pdd_zref=pdd, m_plus=m_plus, m_minus=m_minus,
                          k_elec=k_elec, k_pol_q0=k_pol_q0, m_pol=m_user, m1_ks=m1_ks, pulsed_scanned=pulsed_scanned,
                          c_pl=num(f.get("c_pl"), "cpl", required=False, lo=0.5, hi=1.5) or 1.0,
                          h_pl=num(f.get("h_pl"), "hpl", required=False, lo=0.5, hi=1.5) or 1.0,
                          q0_is_co60=q0_co60,
                          r50_q0=None if q0_co60 else num(f.get("r50_q0"), "R50 калибровочного пучка", lo=0.5, hi=12))
            if t0 is not None:
                kwargs["t0_c"] = t0
            if p0 is not None:
                kwargs["p0_kpa"] = p0
            r = el.calculate(el.ElectronInput(**kwargs))
            quality, k_vol = r50, 1.0
    except ph.OutOfRangeError as e:
        raise InputError(str(e)) from None
    except (ValueError, ZeroDivisionError) as e:
        if isinstance(e, InputError):
            raise
        raise InputError(f"Ошибка расчёта: {e}") from None

    if r.dw_zmax is None and r.deviation_pct is None:
        raise InputError("Не удалось рассчитать Dw(zmax): проверьте PDD или TMR (для SAD можно задать ожидаемую дозу в «Оборудовании»)")
    res = {k: getattr(r, k) for k in ("k_tp", "k_elec", "k_pol", "k_s", "k_q", "m_corrected", "dw_zref",
                                      "dw_zmax", "deviation_pct", "formula_version", "tables_version")}
    res["k_vol"] = k_vol
    extra = {"form": {k: v for k, v in f.items() if v not in (None, "") and k != "csrf"}}
    if modality == "electron":
        extra["r50w"], extra["zref"], extra["h_pl"] = r.r50w, r.zref, r.h_pl
    return quality, res, extra, asdict(r)


# --------------------------------------------------------------------------- live values for the form
def live(modality: str, f: dict, beam: dict | None, calib: dict | None, chamber_name: str | None) -> dict:
    """Intermediate values for the cyan cells of the entry form.

    Every value is computed on its own, so a partly filled form still shows what can be shown.
    Keys are cell ids (without the `live_` prefix); values are display strings with decimal commas.
    """
    from app import protocol as pr

    out: dict[str, str] = {}

    def attempt(key, fn):
        try:
            value = fn()
            if value is not None:
                out[key] = value
        except (InputError, ValueError, ZeroDivisionError, KeyError, ph.OutOfRangeError, TypeError):
            pass

    def n(name, label=None, **kw):
        kw["required"] = False                       # a half-filled or mistyped field just yields no value
        try:
            return num(f.get(name), label or name, **kw)
        except InputError:
            return None

    photon = modality == "photon"
    cid = None
    if chamber_name:
        try:
            cid = core_chamber_id(modality, chamber_name)
        except InputError:
            pass
    ps = bool(f.get("pulsed_scanned"))

    def mean_of(name):
        try:
            vals = readings(f.get(name), name, required=False)
        except InputError:
            return None
        return sum(vals) / len(vals) if vals else None

    m1, m2, mp, mm = (mean_of(k) for k in ("m1", "m2", "m_plus", "m_minus"))
    try:
        up = readings(f.get("m_user"), "M", required=False)
    except InputError:
        up = None
    m_user = (sum(up) / len(up) if up else None) or m1
    m1_ks = mean_of("m1_v1") or m1
    mu = n("mu")
    t0 = n("t0") or (22.0 if photon else 20.0)
    p0 = n("p0") or ph.P0_KPA

    quality = None
    if photon:
        def from_pdd():
            pdd10 = n("pdd10")
            if pdd10 is None or (beam and not beam["fff"] and n("pdd20") is None):
                return None
            return ph.beam_quality_tpr(bool(beam and beam["fff"]), pdd10, n("pdd20"))

        def q():
            tpr = n("tpr")
            entered = tpr is not None
            if tpr is None:
                tpr = from_pdd()
                if tpr is None:
                    return None
            nonlocal quality
            quality = tpr
            return pr.f(tpr, 4)
        attempt("q", q)

        def qsrc():
            """Which value of Q goes into the calculation, and a warning when the two ways disagree."""
            tpr, calc = n("tpr"), None
            try:
                calc = from_pdd()
            except (InputError, ValueError, ZeroDivisionError, KeyError, TypeError):
                pass
            if tpr is not None:
                if calc is not None and abs(calc - tpr) > 0.003:
                    return f"введено; по PDD было бы {pr.f(calc, 4)}: проверьте"
                return "введено вручную"
            return "рассчитано по PDD" if calc is not None else None
        attempt("qsrc", qsrc)
    else:
        def r50w():
            nonlocal quality
            r50 = n("r50")
            if r50 is None:
                return None
            quality = el.beam_quality_r50w(r50, n("c_pl") or 1.0)
            out["zref"] = pr.f(el.z_ref(quality), 3)
            return pr.f(quality, 3)
        attempt("r50w", r50w)

    for key, val in (("m1avg", m1), ("m2avg", m2), ("mpavg", mp), ("mmavg", mm), ("muavg", m_user), ("m1ksavg", m1_ks)):
        if val is not None:
            out[key] = pr.f(val, 4)
    if m1 is not None and mu:
        out["mper"] = pr.f(m1 / mu, 4)
    pressure, temp = n("pressure"), n("temp")
    if pressure and temp is not None:
        out["ktp"] = pr.f(ph.k_tp(pressure, temp, p0, t0), 4)
    if m_user and mp is not None and mm is not None:
        out["kpol"] = pr.f(ph.k_pol(mp, mm, m_user, n("k_pol_q0") or 1.0), 4)
    v1, v2 = n("v1"), n("v2")
    if v1 and v2:
        out["vr"] = pr.f(v1 / v2, 4)
    if m1_ks and m2:
        out["mr"] = pr.f(m1_ks / m2, 4)
    if v1 and v2 and m1_ks and m2:
        def coefs():
            a0, a1, a2 = ph.ks_coefficients(v1 / v2, ps)
            out.update(a0=pr.f(a0, 4), a1=pr.f(a1, 4), a2=pr.f(a2, 4))
            return pr.f(ph.k_s(m1_ks, m2, v1, v2, ps), 4)
        attempt("ks", coefs)
    if photon and cid:
        info = pr._chamber_info("photon", chamber_name)
        zref = n("zref") or 10.0
        dist = n("ref_distance") or 100.0
        out["rid"] = pr.g(dist + zref)
        out["L"] = pr.g(info.get("cavity_length_cm"))
        if quality is not None:
            out["kvol"] = pr.f(ph.k_vol(beam["fff"], quality, dist, zref, info.get("cavity_length_cm")), 4)
    if cid and quality is not None:
        if photon:
            attempt("kq", lambda: pr.f(ph.k_q(cid, quality), 4))
        else:
            q0_co60 = bool(f.get("q0_is_co60"))
            r50q0 = n("r50_q0")
            if q0_co60:
                attempt("kq", lambda: pr.f(el.k_q_co60(cid, quality), 4))
            elif r50q0:
                attempt("kq", lambda: pr.f(el.k_q_qint(cid, quality) / el.k_q_qint(cid, r50q0), 4))
    return out
