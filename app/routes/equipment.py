"""Equipment: linacs, beams, chambers with calibrations, reference values."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auditlog, dbops, fields, services
from app.common import REFERENCE_SAVED, beam_label, calibration_state
from app.db import audit, get_db
from app.web import check_csrf, current_user, form_data, int_or_404, render, require

router = APIRouter()


# ---------------------------------------------------------------- equipment
def form_text(form, name):
    """A text cell of a form, checked against the rule of its field (length, allowed signs); an error is a 422."""
    try:
        return fields.check_text(name, form.get(name))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def eq_back(form) -> str:
    """Where to return after a change on the equipment page (the tab and the selected linac), never outside /equipment."""
    back = (form.get("back") or "").strip()
    return back if back.startswith("/equipment") and "//" not in back else "/equipment"


def beam_readiness(b) -> dict:
    """What a beam still lacks to be used smoothly on the calculation sheet: hard (the sheet cannot be completed) and soft (convenience)."""
    hard, soft = [], []
    if b.get("zmax") is None:
        hard.append("zmax")
    if b.get("pdd_zref") is None:
        hard.append("PDD(zref)")
    if not (b.get("field_size") or "").strip():
        soft.append("размер поля")
    if b.get("ref_depth") is None:
        soft.append("референсная глубина")
    if b.get("dose_rate_mu") is None:
        soft.append("мощность дозы")
    if b.get("cal_mu") is None:
        soft.append("MU при калибровке")
    return {"hard": hard, "soft": soft, "state": "bad" if hard else "warn" if soft else "ok"}


@router.get("/equipment", response_class=HTMLResponse)
def equipment(request: Request, tab: str = "beams", linac: str = "", saved: str = "", user=Depends(current_user), conn=Depends(get_db)):
    tab = tab if tab in ("beams", "dosimeters", "reference") else "beams"
    today = date.today()
    linacs = conn.execute("""SELECT l.*, (SELECT count(*) FROM beams b WHERE b.linac_id = l.id) AS n_beams
                             FROM linacs l ORDER BY l.name""").fetchall()
    ctx = dict(tab=tab, linacs=linacs, today=today, q0_options=CAL_Q0, saved=saved if saved.isdigit() else "")
    if tab == "beams":
        current = next((l for l in linacs if str(l["id"]) == linac), linacs[0] if linacs else None)
        all_beams = conn.execute("SELECT b.*, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id WHERE b.linac_id = %s "
                                 "ORDER BY b.modality, b.nominal_energy, b.fff", (current["id"],)).fetchall() if current else []
        for b in all_beams:
            b["records"] = beam_usage(conn, b["id"])
            b["ready"] = beam_readiness(b)
        beams = [b for b in all_beams if not b["archived"]]
        archived_beams = [b for b in all_beams if b["archived"]]
        for l in linacs:
            l["incomplete"] = sum(1 for b in conn.execute("SELECT * FROM beams WHERE linac_id = %s", (l["id"],)).fetchall()
                                  if beam_readiness(b)["state"] == "bad")
        ctx.update(current=current, archived_beams=archived_beams, photon_beams=[b for b in beams if b["modality"] == "photon"],
                   electron_beams=[b for b in beams if b["modality"] == "electron"], beams=beams)
    elif tab == "dosimeters":
        cals = conn.execute("""SELECT cal.*, ch.name AS chamber, cu.serial_no, el.model AS el_model, el.serial_no AS el_sn
            FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
            JOIN chambers ch ON ch.id = cu.chamber_id LEFT JOIN electrometers el ON el.id = cal.electrometer_id
            ORDER BY ch.name, cu.serial_no, cal.calibrated_on DESC""").fetchall()
        units = {}
        for c in cals:
            c["used"] = conn.execute("SELECT count(*) AS n FROM measurement_sessions WHERE calibration_id = %s",
                                     (c["id"],)).fetchone()["n"]
            c["nd_warn"] = services.nd_w_warning(c["chamber"], c["nd_w"])
            c["state"] = calibration_state(c, today)
            units.setdefault((c["chamber"], c["serial_no"]), []).append(c)
        unit_rows = [dict(chamber=k[0], serial_no=k[1], cals=v, current=v[0], state=v[0]["state"]) for k, v in units.items()]
        electrometers = conn.execute("""SELECT el.*, (SELECT count(*) FROM calibrations c WHERE c.electrometer_id = el.id) AS n_cals
                                        FROM electrometers el ORDER BY el.model, el.serial_no""").fetchall()
        ctx.update(unit_rows=unit_rows, electrometers=electrometers,
                   chambers=conn.execute("SELECT id, name FROM chambers ORDER BY name").fetchall())
    else:
        refs = conn.execute("""SELECT r.*, b.modality, b.nominal_energy, b.fff, l.name AS linac, ch.name AS chamber, cu.serial_no,
                                      u.full_name AS who
            FROM beam_reference r JOIN beams b ON b.id = r.beam_id JOIN linacs l ON l.id = b.linac_id
            JOIN chamber_units cu ON cu.id = r.chamber_unit_id JOIN chambers ch ON ch.id = cu.chamber_id
            JOIN users u ON u.id = r.set_by ORDER BY l.name, b.modality, b.nominal_energy, b.fff, ch.name""").fetchall()
        for r in refs:
            r["label"] = ("γ " if r["modality"] == "photon" else "e⁻ ") + beam_label(r)
        ctx.update(refs=refs, ref_fields=REFERENCE_SAVED)
    return render(request, "equipment.html", user, **ctx)


@router.post("/equipment/reference/delete")
def delete_reference(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    row = conn.execute("DELETE FROM beam_reference WHERE beam_id = %s AND chamber_unit_id = %s RETURNING beam_id",
                       (int_or_404(form.get("beam_id"), "Пучок"), int_or_404(form.get("chamber_unit_id"), "Камера"))).fetchone()
    if not row:
        raise HTTPException(404, "Опорные значения не найдены")
    audit(conn, user["id"], "delete_beam_reference", "beams", row["beam_id"], {"chamber_unit_id": form.get("chamber_unit_id")})
    return RedirectResponse(eq_back(form), status_code=303)


def beam_usage(conn, beam_id):
    """Records of a beam: all, the locked ones (approved, superseded, annulled: history) and the imported journal rows."""
    return conn.execute("""SELECT (SELECT count(*) FROM measurement_sessions WHERE beam_id = %s) AS sessions,
                                  (SELECT count(*) FROM measurement_sessions WHERE beam_id = %s AND status NOT IN ('draft', 'returned')) AS locked,
                                  (SELECT count(*) FROM legacy_journal WHERE beam_id = %s) AS legacy""",
                        (beam_id, beam_id, beam_id)).fetchone()


@router.post("/equipment/linac/{lid}/rename")
def rename_linac(request: Request, lid: str, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    name = form_text(form, "name")
    if not name:
        raise HTTPException(422, "Название аппарата не может быть пустым")
    lid = int_or_404(lid, "Аппарат")
    if conn.execute("SELECT 1 FROM linacs WHERE name = %s AND id <> %s", (name, lid)).fetchone():
        raise HTTPException(409, "Аппарат с таким названием уже есть")
    before = conn.execute("SELECT * FROM linacs WHERE id = %s", (lid,)).fetchone()
    row = conn.execute("""UPDATE linacs SET name = %s, site = NULLIF(%s, ''), model = NULLIF(%s, ''),
                           serial_no = NULLIF(%s, ''), city = NULLIF(%s, '') WHERE id = %s RETURNING id""",
                       (name, form_text(form, "site") or "", form_text(form, "model") or "",
                        form_text(form, "serial_no") or "", form_text(form, "city") or "", lid)).fetchone()
    if not row:
        raise HTTPException(404, "Аппарат не найден")
    after = conn.execute("SELECT * FROM linacs WHERE id = %s", (lid,)).fetchone()
    audit(conn, user["id"], "rename_linac", "linacs", lid, {"changes": auditlog.as_json(auditlog.diff(before or {}, after))})
    return RedirectResponse(eq_back(form), status_code=303)


@router.post("/equipment/linac/{lid}/delete")
def delete_linac(request: Request, lid: str, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    lid = int_or_404(lid, "Аппарат")
    n = conn.execute("SELECT count(*) AS n FROM beams WHERE linac_id = %s", (lid,)).fetchone()["n"]
    if n:
        raise HTTPException(409, f"У аппарата есть пучки ({n}). Сначала удалите пучки (без записей) "
                                 "или переименуйте аппарат вместо удаления")
    if not conn.execute("DELETE FROM linacs WHERE id = %s RETURNING id", (lid,)).fetchone():
        raise HTTPException(404, "Аппарат не найден")
    audit(conn, user["id"], "delete_linac", "linacs", lid)
    return RedirectResponse(eq_back(form), status_code=303)


@router.post("/equipment/beam/{bid}/delete")
def delete_beam(request: Request, bid: str, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    bid = int_or_404(bid, "Пучок")
    use = beam_usage(conn, bid)
    if use["sessions"] or use["legacy"]:
        raise HTTPException(409, f"У пучка есть данные: измерений {use['sessions']}, исторических записей {use['legacy']}. "
                                 "Отправьте пучок в архив; если все записи пучка черновики, его можно удалить вместе с ними")
    conn.execute("DELETE FROM spc_baseline WHERE beam_id = %s", (bid,))
    if not conn.execute("DELETE FROM beams WHERE id = %s RETURNING id", (bid,)).fetchone():
        raise HTTPException(404, "Пучок не найден")
    audit(conn, user["id"], "delete_beam", "beams", bid)
    return RedirectResponse(eq_back(form), status_code=303)


@router.post("/equipment/beam/{bid}/archive")
def archive_beam(request: Request, bid: str, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    """A beam entered by mistake (or no longer used) leaves the choices of a new measurement; its records stay."""
    check_csrf(request, form)
    bid = int_or_404(bid, "Пучок")
    on = form.get("archived") != "0"
    row = conn.execute("""UPDATE beams SET archived = %s, archived_at = CASE WHEN %s THEN now() END,
                          archived_by = CASE WHEN %s THEN %s END WHERE id = %s RETURNING id""",
                       (on, on, on, user["id"], bid)).fetchone()
    if not row:
        raise HTTPException(404, "Пучок не найден")
    audit(conn, user["id"], "archive_beam" if on else "restore_beam", "beams", bid)
    return RedirectResponse(eq_back(form), status_code=303)


@router.post("/equipment/beam/{bid}/purge")
def purge_beam(request: Request, bid: str, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    """Delete a beam together with its drafts and returned records (never approved, superseded or annulled ones)."""
    check_csrf(request, form)
    bid = int_or_404(bid, "Пучок")
    use = beam_usage(conn, bid)
    if use["locked"]:
        raise HTTPException(409, f"У пучка есть утверждённые, замещённые или аннулированные записи ({use['locked']}): это история, "
                                 "удалить их нельзя. Отправьте пучок в архив")
    if use["legacy"] and not form.get("with_legacy"):
        raise HTTPException(409, f"У пучка есть импортированные записи журнала ({use['legacy']}): отметьте их удаление или отправьте пучок в архив")
    try:
        dbops.delete_beam_with_drafts(conn, bid, user["id"], bool(form.get("with_legacy")))
    except dbops.MaintenanceError as e:
        raise HTTPException(409, str(e)) from None
    return RedirectResponse(eq_back(form), status_code=303)


@router.post("/equipment/calibration/{cid}/delete")
def delete_calibration(request: Request, cid: str, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    cid = int_or_404(cid, "Калибровка")
    used = conn.execute("SELECT count(*) AS n FROM measurement_sessions WHERE calibration_id = %s",
                        (cid,)).fetchone()["n"]
    if used:
        raise HTTPException(409, f"Калибровка используется в измерениях ({used}); удалить её нельзя")
    row = conn.execute("DELETE FROM calibrations WHERE id = %s RETURNING chamber_unit_id", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "Калибровка не найдена")
    conn.execute("""DELETE FROM chamber_units WHERE id = %s
                    AND NOT EXISTS (SELECT 1 FROM calibrations WHERE chamber_unit_id = %s)""",
                 (row["chamber_unit_id"], row["chamber_unit_id"]))
    audit(conn, user["id"], "delete_calibration", "calibrations", cid)
    return RedirectResponse(eq_back(form), status_code=303)


@router.post("/equipment/linac")
def add_linac(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    name = form_text(form, "name")
    if not name:
        raise HTTPException(422, "Укажите название аппарата")
    conn.execute("""INSERT INTO linacs(name, site, model, serial_no, city)
                    VALUES (%s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, '')) ON CONFLICT (name) DO NOTHING""",
                 (name, form_text(form, "site") or "", form_text(form, "model") or "",
                  form_text(form, "serial_no") or "", form_text(form, "city") or ""))
    audit(conn, user["id"], "add_linac", "linacs", name)
    return RedirectResponse(eq_back(form), status_code=303)


@router.post("/equipment/beam")
def add_beam(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    modality = form.get("modality")
    if modality not in ("photon", "electron"):
        raise HTTPException(422, "Неизвестный тип пучка")
    try:
        energy = services.num(form.get("energy"), "Энергия", lo=0.1, hi=50)
    except services.InputError as e:
        raise HTTPException(422, str(e)) from None
    conn.execute("""INSERT INTO beams(linac_id, modality, nominal_energy, fff) VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING""",
                 (int_or_404(form.get("linac_id"), "Аппарат"), modality, energy,
                  bool(form.get("fff")) and modality == "photon"))
    audit(conn, user["id"], "add_beam", "beams", None, {"modality": modality, "energy": energy})
    return RedirectResponse(eq_back(form), status_code=303)


CAL_Q0 = ("Co-60", "электронный пучок", "фотонный")


def _pol(form, prefix):
    text = ("+" if form.get(prefix + "_plus") else "") + ("−" if form.get(prefix + "_minus") else "")
    return text or None


def parse_calibration(form, conn):
    """Validated column values of a calibration from the equipment form (create and edit share it)."""
    def number(name, label, lo, hi, required=False):
        if name in fields.FIELDS:                     # the limits come from the table of fields (app/fields.py)
            lo, hi = fields.limits(name)
        try:
            return services.num(form.get(name), label, required=required, lo=lo, hi=hi)
        except services.InputError as e:
            raise HTTPException(422, str(e)) from None

    def day(name, label, required=False, past=False):
        text = (form.get(name) or "").strip()
        if not text:
            if required:
                raise HTTPException(422, f"Укажите: {label}")
            return None
        try:
            value = date.fromisoformat(text)
        except ValueError:
            raise HTTPException(422, f"«{label}»: дата в формате ГГГГ-ММ-ДД") from None
        if past and value > date.today():
            raise HTTPException(422, f"«{label}»: дата {value:%d.%m.%Y} позже сегодняшней")
        return value

    q0 = form.get("q0") or "Co-60"
    if q0 not in CAL_Q0:
        raise HTTPException(422, "Неизвестное качество калибровки Q0")
    separate = bool(form.get("kelec_separate"))
    k_elec = number("k_elec", "kelec", 0.5, 1.5)
    if separate and k_elec is None:
        raise HTTPException(422, "Электрометр калибруется отдельно: укажите kelec из свидетельства (например, ВНИИФТРИ)")
    r50_q0 = number("r50_q0", "R50 калибровочного пучка", 0.5, 12)
    if q0 == "электронный пучок" and r50_q0 is None:
        raise HTTPException(422, "Калибровка в электронном пучке: укажите его R50,w")
    el_model, el_sn = form_text(form, "el_model") or "", form_text(form, "el_sn") or ""
    electrometer_id = None
    if el_model or el_sn:
        if not (el_model and el_sn):
            raise HTTPException(422, "Укажите и модель, и серийный номер электрометра (или оставьте оба поля пустыми)")
        conn.execute("INSERT INTO electrometers(model, serial_no) VALUES (%s, %s) ON CONFLICT DO NOTHING", (el_model, el_sn))
        electrometer_id = conn.execute("SELECT id FROM electrometers WHERE model = %s AND serial_no = %s",
                                       (el_model, el_sn)).fetchone()["id"]

    def text(name):
        return form_text(form, name)
    return dict(
        nd_w=number("nd_w", "ND,w", 1e-6, 1000, required=True), k_elec=1.0 if k_elec is None else k_elec,
        kelec_separate=separate, lab=text("lab"), calibrated_on=day("calibrated_on", "дата калибровки", True, past=True),
        valid_until=day("valid_until", "действует до"), q0=q0, r50_q0=r50_q0,
        cal_depth=number("cal_depth", "калибровочная глубина", 0, 30), p0=number("p0", "P0", 80, 110),
        t0=number("t0", "T0", 0, 40), cal_rh=number("cal_rh", "влажность при калибровке", 0, 100),
        voltage_v=number("voltage_v", "V1 при калибровке", -3000, 3000), polarity_cal=_pol(form, "pol_cal"),
        cal_pol_corrected=bool(form.get("cal_pol_corrected")), polarity_user=_pol(form, "pol_user"),
        el_range=text("el_range"), kelec_lab=text("kelec_lab"), kelec_date=day("kelec_date", "дата калибровки электрометра", past=True),
        electrometer_id=electrometer_id)


@router.post("/equipment/calibration")
def add_calibration(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    serial = form_text(form, "serial_no")
    if not serial:
        raise HTTPException(422, "Укажите серийный номер камеры")
    chamber_id = int_or_404(form.get("chamber_id"), "Камера")
    values = parse_calibration(form, conn)
    conn.execute("INSERT INTO chamber_units(chamber_id, serial_no) VALUES (%s, %s) ON CONFLICT DO NOTHING", (chamber_id, serial))
    unit = conn.execute("SELECT id FROM chamber_units WHERE chamber_id = %s AND serial_no = %s", (chamber_id, serial)).fetchone()
    cols = list(values)
    row = conn.execute(f"INSERT INTO calibrations(chamber_unit_id, {', '.join(cols)}) "
                       f"VALUES (%s, {', '.join(['%s'] * len(cols))}) RETURNING id",
                       [unit["id"]] + [values[c] for c in cols]).fetchone()
    audit(conn, user["id"], "add_calibration", "calibrations", row["id"])
    return RedirectResponse(eq_back(form), status_code=303)


def calibration_row(conn, cid):
    row = conn.execute("""SELECT cal.*, ch.name AS chamber, cu.serial_no, el.model AS el_model, el.serial_no AS el_sn
        FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id JOIN chambers ch ON ch.id = cu.chamber_id
        LEFT JOIN electrometers el ON el.id = cal.electrometer_id WHERE cal.id = %s""", (int_or_404(cid, "Калибровка"),)).fetchone()
    if not row:
        raise HTTPException(404, "Калибровка не найдена")
    row["used"] = conn.execute("SELECT count(*) AS n FROM measurement_sessions WHERE calibration_id = %s",
                               (row["id"],)).fetchone()["n"]
    return row


@router.get("/equipment/calibration/{cid}/edit", response_class=HTMLResponse)
def edit_calibration_form(request: Request, cid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    c = calibration_row(conn, cid)
    return render(request, "calibration_edit.html", user, c=c, q0_options=CAL_Q0)


@router.post("/equipment/calibration/{cid}/edit")
def edit_calibration(request: Request, cid: str, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    c = calibration_row(conn, cid)
    if c["used"]:
        raise HTTPException(409, f"Калибровка используется в измерениях ({c['used']}): менять её нельзя, чтобы не исказить "
                                 "протоколы. Добавьте новую калибровку (новый сертификат) с нужными значениями")
    values = parse_calibration(form, conn)
    conn.execute(f"UPDATE calibrations SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s",
                 list(values.values()) + [c["id"]])
    audit(conn, user["id"], "edit_calibration", "calibrations", c["id"], {"changes": auditlog.as_json(auditlog.diff(c, values))})
    return RedirectResponse(eq_back(form), status_code=303)


@router.post("/equipment/beam/{bid}/params")
def beam_params(request: Request, bid: str, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)

    def number(name, *_unused):          # the limits come from the table of fields (app/fields.py)
        f = fields.FIELDS[name]
        try:
            return services.num(form.get(name), f.label, required=False, lo=f.lo, hi=f.hi)
        except services.InputError as e:
            raise HTTPException(422, str(e)) from None
    before = conn.execute("SELECT * FROM beams WHERE id = %s", (int_or_404(bid, "Пучок"),)).fetchone()
    expected = number("exp_cgy_mu")
    zref_in, depth_in = number("exp_zref"), number("ref_depth")                      # both are checked even if only one is used
    exp_depth = (zref_in or depth_in) if expected else None                         # the depth of the reference point is the reference depth of the beam
    row = conn.execute("""UPDATE beams SET dose_rate_mu = %s, field_size = NULLIF(%s, ''), phantom = NULLIF(%s, ''),
                          c_pl = %s, h_pl = %s, zmax = %s, window_material = NULLIF(%s, ''),
                          window_thickness = %s, pdd_zref = %s, tmr_zref = %s, exp_cgy_mu = %s, exp_zref = %s,
                          exp_source = NULLIF(%s, ''), cal_mu = %s, ref_depth = %s WHERE id = %s RETURNING id""",
                       (number("dose_rate", "мощность дозы", 1, 100000), form_text(form, "field_size") or "",
                        form_text(form, "phantom") or "", number("c_pl", "cpl", 0.5, 1.5), number("h_pl", "hpl", 0.5, 1.5),
                        number("zmax", "zmax", 0, 30), form_text(form, "window_material") or "",
                        number("window_thickness", "толщина окна", 0, 10), number("pdd_zref", "PDD(zref)", 30, 100),
                        number("tmr_zref", "TMR(zref)", 0.1, 1.5), expected,
                        exp_depth, form_text(form, "exp_source") or "",
                        number("cal_mu", "MU при калибровке", 1, 100000), number("ref_depth", "референсная глубина", 0.5, 30),
                        int_or_404(bid, "Пучок"))).fetchone()
    if not row:
        raise HTTPException(404, "Пучок не найден")
    after = conn.execute("SELECT * FROM beams WHERE id = %s", (row["id"],)).fetchone()
    audit(conn, user["id"], "beam_params", "beams", row["id"], {"changes": auditlog.as_json(auditlog.diff(before or {}, after))})
    back = eq_back(form)
    return RedirectResponse(f"{back}{'&' if '?' in back else '?'}saved={row['id']}#b{row['id']}", status_code=303)      # back to the same row
