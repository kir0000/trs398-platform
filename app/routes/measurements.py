"""Measurements: the list, the worksheet (preview, save, edit), review, replacement, deleting and annulling, print and PDF."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app import auditlog, dbops, protocol, services
from app.common import REFERENCE_SAVED, beam_label, beam_periods, calibration_reminders, trend_points, unc_settings
from app.db import Jsonb, audit, get_db
from app.pdf import PdfUnavailable, html_to_pdf
from app.security import can_create, can_review
from app.web import check_csrf, current_user, form_data, int_or_404, render, require, STATUS_LABELS

router = APIRouter()


# ---------------------------------------------------------------- measurements
SESSION_SELECT = """
SELECT s.*, b.modality, b.nominal_energy, b.fff, l.name AS linac, l.model AS linac_model, l.serial_no AS linac_serial,
       el.model AS el_model, el.serial_no AS el_sn, cal.kelec_separate, ch.name AS chamber, cu.serial_no,
       cal.nd_w, cal.k_elec AS cal_k_elec, cal.lab AS cal_lab, cal.voltage_v AS cal_voltage, cal.calibrated_on, cal.q0 AS cal_q0,
       uc.full_name AS creator, ua.full_name AS approver
FROM measurement_sessions s
JOIN beams b ON b.id = s.beam_id
JOIN linacs l ON l.id = b.linac_id
JOIN calibrations cal ON cal.id = s.calibration_id
LEFT JOIN electrometers el ON el.id = cal.electrometer_id
JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
JOIN chambers ch ON ch.id = cu.chamber_id
JOIN users uc ON uc.id = s.created_by
LEFT JOIN users ua ON ua.id = s.approved_by
"""


def get_session_row(conn, sid):
    row = conn.execute(SESSION_SELECT + " WHERE s.id = %s", (int_or_404(sid),)).fetchone()
    if not row:
        raise HTTPException(404, "Запись не найдена")
    return row


def load_choices(conn, modality):
    beams = conn.execute("""SELECT b.*, l.name AS linac, l.model AS linac_model, l.serial_no AS linac_serial, l.city AS city
                            FROM beams b JOIN linacs l ON l.id = b.linac_id
                            WHERE b.modality = %s AND NOT b.archived ORDER BY l.name, b.nominal_energy, b.fff""", (modality,)).fetchall()
    for b in beams:
        b["label"] = beam_label(b)
    supported = set(services.chamber_names()[modality])
    cals = [c for c in conn.execute("""
        SELECT cal.*, ch.name, cu.serial_no, el.model AS el_model, el.serial_no AS el_sn
        FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
        JOIN chambers ch ON ch.id = cu.chamber_id LEFT JOIN electrometers el ON el.id = cal.electrometer_id
        ORDER BY cal.calibrated_on DESC""").fetchall()
        if c["name"] in supported]
    for c in cals:
        c["expired"] = bool(c["valid_until"] and c["valid_until"] < date.today())
        c["nd_warn"] = services.nd_w_warning(c["name"], c["nd_w"])
        info = protocol._chamber_info(modality, c["name"])
        c["wall"] = " ".join(x for x in (str(info.get("wall_material") or ""),
                                         f"{info['wall_thickness']:g} г/см²" if info.get("wall_thickness") else "") if x)
        c["cavity"] = f"{info['cavity_length_cm']:g} см" if info.get("cavity_length_cm") else ""
        c["wallm"] = str(info.get("wall_material") or "")
        c["wallt"] = f"{info['wall_thickness']:g}" if info.get("wall_thickness") else ""
        c["v1"] = f"{c['voltage_v']:g}" if c["voltage_v"] is not None else ""
        c["kelec_eff"] = services.effective_kelec(c)
        c["info"] = "; ".join(x for x in (
            f"стенка: {c['wall']}" if c["wall"] else "", f"длина полости L: {c['cavity']}" if c["cavity"] else "",
            f"ND,w = {c['nd_w']} Гр/нКл", f"kelec = {c['k_elec']}", f"Q0: {c['q0']}",
            f"V1 калибровки: {c['voltage_v']:g} В" if c["voltage_v"] is not None else "",
            f"лаборатория: {c['lab']}" if c["lab"] else "",
            f"калибровка {c['calibrated_on']:%d.%m.%Y}",
            f"действует до {c['valid_until']:%d.%m.%Y}" if c["valid_until"] else "") if x)
    return beams, cals


def _g(v):
    return None if v is None else f"{float(v):g}".replace(".", ",")


def equipment_values(conn, modality, beam, calib):
    """Parameters of worksheet sections 1-3 come from Equipment; the calculation sheet cannot change them.

    Returned values replace whatever the browser sent. Empty equipment fields are left out (the defaults apply),
    so records can still be made for equipment that is only partly described.
    """
    linac = conn.execute("SELECT city FROM linacs WHERE id = %s", (beam["linac_id"],)).fetchone() or {}
    el = conn.execute("SELECT model, serial_no FROM electrometers WHERE id = %s", (calib.get("electrometer_id"),)).fetchone()         if calib.get("electrometer_id") else None
    vals = {
        "city": linac.get("city"), "dose_rate": _g(beam.get("dose_rate_mu")), "field_size": beam.get("field_size"),
        "phantom": beam.get("phantom"), "window_material": beam.get("window_material"),
        "window_thickness": _g(beam.get("window_thickness")), "c_pl": _g(beam.get("c_pl")), "h_pl": _g(beam.get("h_pl")), "zmax": _g(beam.get("zmax")),
        "exp_cgy_mu": _g(beam.get("exp_cgy_mu")), "exp_zref": _g(beam.get("exp_zref")), "exp_source": beam.get("exp_source"),
        "cal_depth": _g(calib.get("cal_depth")), "p0": _g(calib.get("p0")), "t0": _g(calib.get("t0")),
        "cal_rh": _g(calib.get("cal_rh")), "polarity_cal": calib.get("polarity_cal"), "polarity_user": calib.get("polarity_user"),
        "electrometer_range": calib.get("el_range"), "r50_q0": _g(calib.get("r50_q0")),
        "kelec_lab": calib.get("kelec_lab"), "kelec_date": calib["kelec_date"].isoformat() if calib.get("kelec_date") else None,
        "electrometer_model": el["model"] if el else None, "electrometer_sn": el["serial_no"] if el else None,
        "kelec_separate": "1" if calib.get("kelec_separate") else None,
        "cal_pol_corrected": "1" if calib.get("cal_pol_corrected") else None,
    }
    out = {k: str(v) for k, v in vals.items() if v not in (None, "")}
    if modality == "electron":
        out["q0_is_co60"] = "1" if (calib.get("q0") or "Co-60") == "Co-60" else ""
    return out


def pick(conn, table, ident, what):
    row = conn.execute(f"SELECT * FROM {table} WHERE id = %s", (int_or_404(ident, what),)).fetchone()
    if not row:
        raise HTTPException(422, f"{what}: не выбрано")
    return row


def reference_key(modality, geometry, f, beam):
    """Identifies the series of a record in the trends. SSD: the dose at zmax per MU (one definition for all). SAD: the dose at the
    reference point compared with the planning-system value, so the depth, the field and the expected value are part of the key:
    values from different reference conditions are never mixed. SAD without an expected value (the old TMR way): 'SAD|old'."""
    if modality != "photon" or geometry != "SAD":
        return "SSD"
    try:
        expected = float(str(f.get("exp_cgy_mu") or "").replace(",", "."))
    except ValueError:
        expected = None
    if not expected:
        return "SAD|old"
    zref = services.num(f.get("zref"), "zref", required=False, lo=1, hi=20) or 10.0
    field = " ".join((beam.get("field_size") or "").lower().replace("х", "x").replace("×", "x").split())
    return f"SAD|z={zref:g}|{field}|{expected:g}"


def prepare(conn, modality, f):
    """Validate the form and compute. Returns (db_values, results, extra)."""
    if modality not in ("photon", "electron"):
        raise HTTPException(404, "Неизвестный тип пучка")
    beam = pick(conn, "beams", f.get("beam_id"), "Пучок")
    if beam["modality"] != modality:
        raise services.InputError("Выбранный пучок не соответствует типу измерения")
    calib = pick(conn, "calibrations", f.get("calibration_id"), "Калибровка камеры")
    if calib["valid_until"] and calib["valid_until"] < date.today():
        raise services.InputError(f"Срок действия калибровки камеры истёк {calib['valid_until']:%d.%m.%Y}: "
                                  "выберите камеру с действующей калибровкой или добавьте новую в разделе «Оборудование»")
    chamber = conn.execute("""SELECT ch.name FROM chamber_units cu JOIN chambers ch ON ch.id = cu.chamber_id
                              WHERE cu.id = %s""", (calib["chamber_unit_id"],)).fetchone()["name"]
    try:
        measured_on = date.fromisoformat(f.get("measured_on") or "")
    except ValueError:
        raise services.InputError("Укажите дату измерения") from None
    if measured_on > date.today():
        raise services.InputError(f"Дата измерения {measured_on:%d.%m.%Y} позже сегодняшней")
    f = services.with_user_series({**f, **equipment_values(conn, modality, beam, calib)})
    for key in ("kelec_separate", "cal_pol_corrected"):       # a snapshot of the equipment state belongs to the record
        f.setdefault(key, "")
    quality, res, extra, _ = services.compute(modality, f, beam, calib, chamber)
    values = dict(
        measured_on=measured_on, beam_id=beam["id"], calibration_id=calib["id"],
        geometry=f.get("geometry", "SSD") if modality == "photon" else "SSD",
        mu=services.num(f.get("mu"), "MU"), pressure_kpa=services.num(f.get("pressure"), "P"),
        temp_c=services.num(f.get("temp"), "T"), humidity_pct=services.num(f.get("humidity"), "RH", required=False, lo=0, hi=100),
        v1=services.num(f.get("v1"), "V1"), v2=services.num(f.get("v2"), "V2"),
        m1_readings=services.readings(f.get("m1"), "M1"), m2_readings=services.readings(f.get("m2"), "M2"),
        m_plus_readings=services.readings(f.get("m_plus"), "M+", required=False),
        m_minus_readings=services.readings(f.get("m_minus"), "M-", required=False),
        beam_quality=quality, pdd_zref=services.num(f.get("pdd_zref"), "PDD", required=False),
        tmr_zref=services.num(f.get("tmr_zref"), "TMR", required=False), note=(f.get("note") or "").strip() or None,
        ref_key=reference_key(modality, f.get("geometry", "SSD"), f, beam),
    )
    return values, res, extra


def save_results(conn, sid, res):
    cols = list(res)
    conn.execute(
        f"INSERT INTO results(session_id, {', '.join(cols)}) VALUES (%s, {', '.join(['%s'] * len(cols))}) "
        f"ON CONFLICT (session_id) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in cols)}, computed_at = now()",
        [sid] + [res[c] for c in cols])


def form_dict(form):
    return {k: v for k, v in form.items() if isinstance(v, str)}


LIST_PAGE_SIZE = 200                                                # records on one page of the list (nothing is cut off: there are pages)


def list_filters(params) -> dict:
    """The filters of the list from the query string: status, linac, beam, dates of the measurement, a text (protocol number, author)."""
    def number(name):
        v = str(params.get(name, ""))
        return int(v) if v.isdigit() else None

    def day(name):
        try:
            return date.fromisoformat(str(params.get(name, "")))
        except ValueError:
            return None
    status = str(params.get("status", ""))
    return {"status": status if status in STATUS_LABELS else "", "linac": number("linac"), "beam": number("beam"),
            "from": day("from"), "to": day("to"), "q": str(params.get("q", "")).strip()[:60]}


def list_where(f: dict) -> tuple[str, list]:
    cond, args = [], []
    for column, key in (("s.status", "status"), ("l.id", "linac"), ("b.id", "beam")):
        if f[key] not in (None, ""):
            cond.append(f"{column} = %s")
            args.append(f[key])
    if f["from"]:
        cond.append("s.measured_on >= %s")
        args.append(f["from"].isoformat())
    if f["to"]:
        cond.append("s.measured_on <= %s")
        args.append(f["to"].isoformat())
    if f["q"]:
        cond.append("(s.protocol_no LIKE %s OR uc.full_name LIKE %s OR uc.login LIKE %s)")
        args += [f"%{f['q']}%"] * 3
    return (" WHERE " + " AND ".join(cond)) if cond else "", args


@router.get("/measurements", response_class=HTMLResponse)
def measurements(request: Request, page: int = 1, user=Depends(current_user), conn=Depends(get_db)):
    f = list_filters(request.query_params)
    where, params = list_where(f)
    base = """FROM measurement_sessions s JOIN beams b ON b.id = s.beam_id JOIN linacs l ON l.id = b.linac_id
        JOIN users uc ON uc.id = s.created_by LEFT JOIN results r ON r.session_id = s.id"""
    total = conn.execute(f"SELECT count(*) AS n {base}{where}", params).fetchone()["n"]
    pages = max(1, -(-total // LIST_PAGE_SIZE))
    page = min(max(page, 1), pages)
    rows = conn.execute(f"""SELECT s.id, s.protocol_no, s.measured_on, s.status, s.created_by, b.modality, b.nominal_energy, b.fff,
        l.name AS linac, uc.full_name AS creator, r.dw_zmax, r.deviation_pct {base}{where}
        ORDER BY s.measured_on DESC, s.id DESC LIMIT {LIST_PAGE_SIZE} OFFSET {(page - 1) * LIST_PAGE_SIZE}""", params).fetchall()
    for r in rows:
        r["label"] = beam_label(r)
    pending = conn.execute("SELECT count(*) AS n FROM measurement_sessions WHERE status = 'submitted'").fetchone()["n"]
    linacs = conn.execute("SELECT id, name FROM linacs ORDER BY name").fetchall()
    beams = conn.execute("""SELECT b.id, b.modality, b.nominal_energy, b.fff, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id
                            ORDER BY l.name, b.modality, b.nominal_energy, b.fff""").fetchall()
    for b in beams:
        b["label"] = ("γ " if b["modality"] == "photon" else "e⁻ ") + beam_label(b)
    query = "&".join(f"{k}={v}" for k, v in request.query_params.items() if k != "page" and v)
    return render(request, "list.html", user, rows=rows, status=f["status"], f=f, pending=pending, total=total, page=page, pages=pages,
                  page_size=LIST_PAGE_SIZE, first_row=(page - 1) * LIST_PAGE_SIZE + 1 if total else 0, linacs=linacs, beams=beams, query=query,
                  reminders=calibration_reminders(conn, date.today()))


@router.get("/measurements/new", response_class=HTMLResponse)
def new_form(request: Request, modality: str = "photon", user=Depends(require("physicist", "admin")),
             conn=Depends(get_db)):
    if modality not in ("photon", "electron"):
        raise HTTPException(404, "Неизвестный тип пучка")
    beams, cals = load_choices(conn, modality)
    return render(request, "form.html", user, modality=modality, beams=beams, cals=cals,
                  f={"measured_on": date.today().isoformat(), "geometry": "SSD", "humidity": "50"}, is_new=True,
                  action="/measurements", title="Новое измерение")


REFERENCE_SERIES = ("m1", "m1_v1", "m_plus", "m_minus", "m2")
REFERENCE_NUMBERS = {"tpr": (0.3, 1.0), "pdd10": (10, 100), "pdd20": (5, 100), "r50": (0.5, 20), "mu": (1, 100000),
                     "v1": (-1500, 1500), "v2": (-1500, 1500)}


def chamber_unit_of(conn, calibration_id):
    row = conn.execute("SELECT chamber_unit_id FROM calibrations WHERE id = %s", (calibration_id,)).fetchone()         if str(calibration_id).isdigit() else None
    return row["chamber_unit_id"] if row else None


@router.get("/measurements/reference")
def reference_series(beam_id: str = "", calibration_id: str = "", source: str = "auto", user=Depends(require("physicist", "admin")),
                     conn=Depends(get_db)):
    """Reference values for a new measurement: the ones a physicist declared for this beam and chamber (source=saved),
    otherwise the first approved measurement of the beam (source=first).

    The corrections (iii) polarity and (iv) recombination are determined once per beam and chamber; later checks reuse them,
    but the user may change them.
    """
    bid = int_or_404(beam_id, "Пучок")
    unit = chamber_unit_of(conn, calibration_id)
    saved = conn.execute("""SELECT r.data, r.set_at, u.full_name FROM beam_reference r JOIN users u ON u.id = r.set_by
                            WHERE r.beam_id = %s AND r.chamber_unit_id = %s""", (bid, unit)).fetchone() if unit else None
    if saved and source in ("auto", "saved"):
        return JSONResponse({"found": True, "kind": "saved", "date": saved["set_at"].strftime("%d.%m.%Y"), "by": saved["full_name"],
                             **{k: saved["data"].get(k, "") for k in REFERENCE_SAVED}})
    if source == "saved":
        return JSONResponse({"found": False, "kind": "saved"})
    base = """SELECT s.*, b.modality FROM measurement_sessions s JOIN beams b ON b.id = s.beam_id
              WHERE s.beam_id = %s AND s.status = 'approved' {extra} ORDER BY s.measured_on, s.id LIMIT 1"""
    row = None
    if calibration_id.isdigit():
        row = conn.execute(base.format(extra="""AND s.calibration_id IN (SELECT c2.id FROM calibrations c2 WHERE
                           c2.chamber_unit_id = (SELECT chamber_unit_id FROM calibrations WHERE id = %s))"""),
                           (bid, int(calibration_id))).fetchone()
    if not row:
        row = conn.execute(base.format(extra=""), (bid,)).fetchone()
    if not row:
        return JSONResponse({"found": False, "kind": "first"})
    f = form_values(row)
    f["m1_v1"] = f.get("m1_v1") or f.get("m1", "")
    f["pulsed_scanned"] = f.get("pulsed_scanned") or ""
    return JSONResponse({"found": True, "kind": "first", "record": row["id"], "date": row["measured_on"].strftime("%d.%m.%Y"),
                         **{k: f.get(k, "") for k in REFERENCE_SAVED}})


@router.post("/measurements/reference")
def save_reference(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    """The values of the open worksheet become the reference of this beam with this chamber unit."""
    check_csrf(request, form)
    bid = int_or_404(form.get("beam_id"), "Пучок")
    unit = chamber_unit_of(conn, form.get("calibration_id"))
    if not unit or not conn.execute("SELECT 1 FROM beams WHERE id = %s", (bid,)).fetchone():
        raise HTTPException(404, "Пучок или калибровка не найдены")
    data = {}
    try:
        for name in REFERENCE_SAVED:
            raw = (form.get(name) or "").strip()
            if not raw:
                continue
            if name in REFERENCE_SERIES:
                services.readings(raw, name)
            elif name in REFERENCE_NUMBERS:
                lo, hi = REFERENCE_NUMBERS[name]
                services.num(raw, name, lo=lo, hi=hi)
            data[name] = raw
    except services.InputError as e:
        raise HTTPException(422, str(e)) from None
    if not any(data.get(k) for k in ("m_plus", "m_minus", "m2")):
        raise HTTPException(422, "Заполните показания (iii) и (iv): иначе опорных значений нет")
    conn.execute("""INSERT INTO beam_reference(beam_id, chamber_unit_id, data, set_by) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (beam_id, chamber_unit_id) DO UPDATE SET data = EXCLUDED.data, set_by = EXCLUDED.set_by, set_at = now()""",
                 (bid, unit, Jsonb(data), user["id"]))
    audit(conn, user["id"], "beam_reference", "beams", bid, {"chamber_unit_id": unit, "fields": sorted(data)})
    return JSONResponse({"ok": True})


@router.post("/measurements/preview", response_class=HTMLResponse)
def preview(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    f = form_dict(form)
    modality = f.get("modality", "")
    if modality not in ("photon", "electron"):
        raise HTTPException(404, "Неизвестный тип пучка")
    cells, res, error, exp_cgy_mu = {}, None, None, None
    try:
        beam = conn.execute("SELECT * FROM beams WHERE id = %s", (int(f.get("beam_id") or 0),)).fetchone()
        calib = conn.execute("SELECT * FROM calibrations WHERE id = %s", (int(f.get("calibration_id") or 0),)).fetchone()
        chamber = None
        if calib:
            chamber = conn.execute("""SELECT ch.name FROM chamber_units cu JOIN chambers ch ON ch.id = cu.chamber_id
                                      WHERE cu.id = %s""", (calib["chamber_unit_id"],)).fetchone()["name"]
        if beam and beam["modality"] == modality:
            if calib:
                f = services.with_user_series({**f, **equipment_values(conn, modality, beam, calib)})
            cells = services.live(modality, f, beam, calib, chamber)
    except ValueError:
        pass
    try:
        _, res, extra = prepare(conn, modality, f)
        exp_cgy_mu = extra["form"].get("exp_cgy_mu") if res.get("dw_zmax") is None else None
        from app import protocol as pr
        cells.update(mq=pr.sci(res["m_corrected"]), dwref=pr.f(res["dw_zref"], 6), dwmax=pr.f(res["dw_zmax"], 6),
                     dev=pr.f(res["deviation_pct"], 2), kq=pr.f(res["k_q"], 4), kelec=pr.f(res["k_elec"], 4))
    except services.InputError as e:
        error = str(e)
    except HTTPException:
        error = "Выберите пучок и калибровку камеры"
    if calib:
        from app import protocol as pr
        cells.setdefault("kelec", pr.f(services.effective_kelec(calib), 4))
    drift = {}
    for key, name in (("dr_m1", "m1"), ("dr_plus", "m_plus"), ("dr_minus", "m_minus"), ("dr_m1ks", "m1_v1"), ("dr_m2", "m2")):
        try:
            stats = services.series_stats(services.readings(f.get(name), name, required=False) or [])
        except services.InputError:
            stats = None
        if stats:
            cells[key] = f"{stats['drift_pct']:+.2f} % ".replace(".", ",") + ("" if stats["status"] == "ok" else "!")
            drift[key] = stats["status"]
    ids = ("q", "qsrc", "r50w", "zref", "m1avg", "m2avg", "mpavg", "mmavg", "muavg", "m1ksavg", "dr_m1", "dr_plus", "dr_minus", "dr_m1ks", "dr_m2", "mper", "ktp", "kpol", "vr", "mr", "a0", "a1", "a2",
           "ks", "rid", "L", "kvol", "kq", "kelec", "mq", "dwref", "dwmax", "dev")
    cells = {i: cells.get(i, "—") for i in ids}                     # cleared fields reset their cells
    return render(request, "_result.html", user, res=res, error=error, cells=cells, drift=drift, exp_cgy_mu=exp_cgy_mu)


@router.post("/measurements")
def create(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    f = form_dict(form)
    modality = f.get("modality", "")
    try:
        values, res, extra = prepare(conn, modality, f)
    except services.InputError as e:
        beams, cals = load_choices(conn, modality)
        return render(request, "form.html", user, status_code=422, modality=modality, beams=beams, cals=cals, f=f,
                      error=str(e), action="/measurements", title="Новое измерение", is_new=True)
    cols = list(values)
    row = conn.execute(
        f"INSERT INTO measurement_sessions({', '.join(cols)}, created_by, extra) "
        f"VALUES ({', '.join(['%s'] * len(cols))}, %s, %s) RETURNING id",
        [values[c] for c in cols] + [user["id"], Jsonb(extra)]).fetchone()
    save_results(conn, row["id"], res)
    audit(conn, user["id"], "create", "measurement", row["id"], {"modality": modality})
    return RedirectResponse(f"/measurements/{row['id']}", status_code=303)


@router.get("/measurements/{sid}", response_class=HTMLResponse)
def detail(request: Request, sid: str, user=Depends(current_user), conn=Depends(get_db)):
    s = get_session_row(conn, sid)
    res = conn.execute("SELECT * FROM results WHERE session_id = %s", (s["id"],)).fetchone()
    mine = s["created_by"] == user["id"]
    return render(request, "detail.html", user, s=s, res=res, beam=beam_label(s), mine=mine,
                  can_edit=mine and s["status"] in ("draft", "returned"),
                  can_decide=can_review(user["role"]) and not mine and s["status"] == "submitted",
                  can_supersede=can_create(user["role"]) and s["status"] == "approved",
                  can_delete=s["status"] in ("draft", "returned") and (mine or user["role"] == "admin") and can_create(user["role"]),
                  can_void=user["role"] == "admin" and s["status"] == "approved")


def unc_choice(value: str) -> str:
    return value if value in ("short", "full", "none") else "short"


def protocol_page(conn, user, sid, kind):
    s = get_session_row(conn, sid)
    res = conn.execute("SELECT * FROM results WHERE session_id = %s", (s["id"],)).fetchone()
    if not res:
        raise HTTPException(409, "Нет рассчитанного результата: протокол сформировать нельзя")
    audit(conn, user["id"], kind, "measurement", s["id"])
    # deviation history of this beam up to (and including) the measurement: approved + imported records
    history = [(p.on, p.deviation_pct) for p in trend_points(conn, s) if p.on <= s["measured_on"]]
    if s["status"] != "approved":
        history.append((s["measured_on"], float(res["deviation_pct"])))        # not in the trend yet
    periods = beam_periods(conn, s["beam_id"])[0]
    return s, res, protocol.build(s, res, history, periods, unc_settings=unc_settings(conn, s["modality"]))


@router.get("/measurements/{sid}/print", response_class=HTMLResponse)
def print_protocol(request: Request, sid: str, unc: str = "short", user=Depends(current_user), conn=Depends(get_db)):
    """unc: how much of the uncertainty analysis goes into the protocol: short (one page, default), full, none."""
    s, res, p = protocol_page(conn, user, sid, "print")
    return render(request, "protocol.html", user, s=s, res=res, v=p, screen=True, unc_mode=unc_choice(unc))


@router.get("/measurements/{sid}/pdf")
def pdf_protocol(request: Request, sid: str, unc: str = "short", user=Depends(current_user), conn=Depends(get_db)):
    s, res, p = protocol_page(conn, user, sid, "pdf")
    html = render(request, "protocol.html", user, s=s, res=res, v=p, screen=False,
                  unc_mode=unc_choice(unc)).body.decode("utf-8")
    try:
        pdf = html_to_pdf(html)
    except PdfUnavailable:
        raise HTTPException(503, "Генерация PDF недоступна: на компьютере не найден Microsoft Edge или Chrome. "
                                 "Используйте «Печать → Сохранить как PDF».") from None
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="TRS398-protocol-{s["id"]}.pdf"'})


def form_values(s):
    """Values for the entry form of an existing record.

    The stored columns are authoritative (records made by the importer or the demo seeder have only those);
    extra.form supplies what has no column (field size, polarity, electrometer range, ...).
    """
    def g(v):
        return "" if v is None else f"{float(v):g}".replace(".", ",")

    def series(vals):
        return " ".join(g(v) for v in (vals or []))

    f = dict(s["extra"].get("form", {}))
    f.update(measured_on=s["measured_on"].isoformat(), beam_id=str(s["beam_id"]), calibration_id=str(s["calibration_id"]),
             note=s["note"] or "", geometry=s["geometry"], mu=g(s["mu"]), pressure=g(s["pressure_kpa"]),
             temp=g(s["temp_c"]), humidity=g(s["humidity_pct"]), v1=g(s["v1"]), v2=g(s["v2"]),
             m1=series(s["m1_readings"]), m2=series(s["m2_readings"]), m_plus=series(s["m_plus_readings"]),
             m_minus=series(s["m_minus_readings"]), pdd_zref=g(s["pdd_zref"]), tmr_zref=g(s["tmr_zref"]))
    if s["modality"] == "electron":
        f["r50"] = g(s["beam_quality"])
    elif not f.get("pdd10") and not f.get("tpr"):      # a TPR derived from PDD stays derived: changing PDD must update it
        f["tpr"] = g(s["beam_quality"])
    return {k: v for k, v in f.items() if v not in (None, "")}


@router.get("/measurements/{sid}/edit", response_class=HTMLResponse)
def edit_form(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    s = get_session_row(conn, sid)
    if s["created_by"] != user["id"] or s["status"] not in ("draft", "returned"):
        raise HTTPException(403, "Редактировать можно только свой черновик или возвращённую запись")
    beams, cals = load_choices(conn, s["modality"])
    f = form_values(s)
    return render(request, "form.html", user, modality=s["modality"], beams=beams, cals=cals, f=f,
                  action=f"/measurements/{s['id']}/edit", title=f"Правка протокола №{s['protocol_no']}", protocol_no=s["protocol_no"])


@router.post("/measurements/{sid}/edit")
def edit(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    if s["created_by"] != user["id"] or s["status"] not in ("draft", "returned"):
        raise HTTPException(403, "Редактировать можно только свой черновик или возвращённую запись")
    f = form_dict(form)
    try:
        values, res, extra = prepare(conn, s["modality"], f)
    except services.InputError as e:
        beams, cals = load_choices(conn, s["modality"])
        return render(request, "form.html", user, status_code=422, modality=s["modality"], beams=beams, cals=cals,
                      f=f, error=str(e), action=f"/measurements/{s['id']}/edit", title=f"Правка записи №{s['id']}")
    cols = list(values)
    if not conn.execute(f"UPDATE measurement_sessions SET {', '.join(f'{c} = %s' for c in cols)}, extra = %s, "
                        f"status = 'draft', review_comment = NULL WHERE id = %s AND status IN ('draft', 'returned')",
                        [values[c] for c in cols] + [Jsonb(extra), s["id"]]).rowcount:
        raise HTTPException(409, "Запись уже изменена другим пользователем: обновите страницу")
    save_results(conn, s["id"], res)
    audit(conn, user["id"], "edit", "measurement", s["id"],
          {"protocol_no": s["protocol_no"], "changes": auditlog.as_json(auditlog.diff(s, values))})
    return RedirectResponse(f"/measurements/{s['id']}", status_code=303)


def _transition(request, sid, user, conn, action, form):
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    comment = (form.get("comment") or "").strip()
    if action == "submit":
        if s["created_by"] != user["id"] or s["status"] not in ("draft", "returned"):
            raise HTTPException(403, "Отправить на проверку может автор черновика")
        if not conn.execute("SELECT 1 FROM results WHERE session_id = %s", (s["id"],)).fetchone():
            raise HTTPException(409, "Нет рассчитанного результата")
        if not conn.execute("UPDATE measurement_sessions SET status = 'submitted' WHERE id = %s AND status IN ('draft', 'returned')", (s["id"],)).rowcount:
            raise HTTPException(409, "Запись уже изменена другим пользователем: обновите страницу")
    else:
        if not can_review(user["role"]):
            raise HTTPException(403, "Недостаточно прав")
        if s["status"] != "submitted":
            raise HTTPException(409, "Запись не находится на проверке")
        if s["created_by"] == user["id"]:
            raise HTTPException(403, "Нельзя утверждать или возвращать собственную запись (правило двух лиц)")
        if action == "approve":
            if not conn.execute("""UPDATE measurement_sessions SET status = 'approved', approved_by = %s, approved_at = now(),
                            review_comment = NULLIF(%s, '') WHERE id = %s AND status = 'submitted'""", (user["id"], comment, s["id"])).rowcount:
                raise HTTPException(409, "Запись уже изменена другим пользователем: обновите страницу")                 # two reviewers at once: the second one is told
            if s["supersedes_id"]:
                conn.execute("UPDATE measurement_sessions SET status = 'superseded' WHERE id = %s",
                             (s["supersedes_id"],))
        else:
            if len(comment) < 3:
                raise HTTPException(422, "При возврате укажите комментарий")
            if not conn.execute("UPDATE measurement_sessions SET status = 'returned', review_comment = %s WHERE id = %s AND status = 'submitted'",
                                (comment, s["id"])).rowcount:
                raise HTTPException(409, "Запись уже изменена другим пользователем: обновите страницу")
    audit(conn, user["id"], action, "measurement", s["id"], {"comment": comment} if comment else {})
    return RedirectResponse(f"/measurements/{s['id']}", status_code=303)


@router.post("/measurements/{sid}/submit")
def submit(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    return _transition(request, sid, user, conn, "submit", form)


@router.post("/measurements/{sid}/approve")
def approve(request: Request, sid: str, user=Depends(require("reviewer", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    return _transition(request, sid, user, conn, "approve", form)


@router.post("/measurements/{sid}/return")
def return_(request: Request, sid: str, user=Depends(require("reviewer", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    return _transition(request, sid, user, conn, "return", form)


@router.post("/measurements/{sid}/supersede")
def supersede(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    reason = (form.get("reason") or "").strip()
    if s["status"] != "approved":
        raise HTTPException(409, "Заменить можно только утверждённую запись")
    if len(reason) < 5:
        raise HTTPException(422, "Укажите причину замены (не короче 5 символов)")
    new = conn.execute("""INSERT INTO measurement_sessions(measured_on, beam_id, calibration_id, geometry, mu,
            pressure_kpa, temp_c, humidity_pct, v1, v2, m1_readings, m2_readings, m_plus_readings, m_minus_readings,
            beam_quality, pdd_zref, tmr_zref, note, created_by, extra, supersedes_id, supersede_reason, ref_key)
        SELECT measured_on, beam_id, calibration_id, geometry, mu, pressure_kpa, temp_c, humidity_pct, v1, v2,
            m1_readings, m2_readings, m_plus_readings, m_minus_readings, beam_quality, pdd_zref, tmr_zref, note,
            %s, extra, id, %s, ref_key FROM measurement_sessions WHERE id = %s AND status = 'approved' RETURNING id""",
                        (user["id"], reason, s["id"])).fetchone()
    if not new:
        raise HTTPException(409, "Запись уже изменена другим пользователем: обновите страницу")
    old = conn.execute("SELECT * FROM results WHERE session_id = %s", (s["id"],)).fetchone()
    if old:
        old.pop("session_id"), old.pop("computed_at")
        save_results(conn, new["id"], old)
    audit(conn, user["id"], "supersede", "measurement", s["id"], {"new_id": new["id"], "reason": reason})
    return RedirectResponse(f"/measurements/{new['id']}/edit", status_code=303)


@router.post("/measurements/{sid}/delete")
def delete_measurement(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    """A draft or a returned record goes away (the author or an admin); the protocol number is not reused and the audit log keeps it."""
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    if s["status"] not in ("draft", "returned"):
        raise HTTPException(409, "Удалить можно только черновик или возвращённую запись; утверждённую можно аннулировать")
    if s["created_by"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "Удалить запись может только её автор или администратор")
    try:
        dbops.delete_draft(conn, s["id"], user["id"])
    except dbops.MaintenanceError as e:
        raise HTTPException(409, str(e)) from None
    return RedirectResponse("/measurements", status_code=303)


@router.post("/measurements/{sid}/void")
def void_measurement(request: Request, sid: str, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    """An approved record is annulled, never deleted: it leaves trends and budgets, the protocol says ANNULLED."""
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    reason = (form.get("reason") or "").strip()
    if s["status"] != "approved":
        raise HTTPException(409, "Аннулировать можно только утверждённую запись")
    if len(reason) < 5:
        raise HTTPException(422, "Укажите причину аннулирования (не короче 5 символов)")
    if not conn.execute("""UPDATE measurement_sessions SET status = 'voided', void_reason = %s, voided_by = %s, voided_at = now()
                           WHERE id = %s AND status = 'approved'""", (reason, user["id"], s["id"])).rowcount:
        raise HTTPException(409, "Запись уже изменена другим пользователем: обновите страницу")
    restored = None
    if s["supersedes_id"]:                  # the correction is annulled: the record it replaced is valid again
        done = conn.execute("UPDATE measurement_sessions SET status = 'approved' WHERE id = %s AND status = 'superseded' RETURNING id",
                            (s["supersedes_id"],)).fetchone()
        restored = done["id"] if done else None
    audit(conn, user["id"], "void", "measurement", s["id"], {"protocol_no": s["protocol_no"], "reason": reason, "restored_id": restored})
    return RedirectResponse(f"/measurements/{s['id']}", status_code=303)
