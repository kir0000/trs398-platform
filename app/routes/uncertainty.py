"""The uncertainty budget: settings, extra components and the page."""
import secrets
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import services
from app.common import beam_label, beam_periods, trend_points, unc_settings
from app.db import audit, get_db
from app.notation import sym
from app.web import check_csrf, current_user, form_data, render, require
from core import electron as el_core
from core import spc, uncertainty
from core import uncertainty_distributions as udist
from core import uncertainty_literature as ulit

router = APIRouter()


# ---------------------------------------------------------------- uncertainty
def _opt_date(text):
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        raise HTTPException(422, "Дата в формате ГГГГ-ММ-ДД") from None


def _opt_float(text, default, name, lo, hi):
    try:
        v = float((text or "").replace(",", ".")) if text else default
    except ValueError:
        raise HTTPException(422, f"«{name}»: не число") from None
    if not lo <= v <= hi:
        raise HTTPException(422, f"«{name}»: допустимо {lo}–{hi}")
    return v


def unc_back(form) -> str:
    back = form.get("back") or "/uncertainty"
    return back if back.startswith("/uncertainty") else "/uncertainty"


def unc_number(text, label):
    try:
        return services.num(text, label, required=True, lo=0, hi=10)
    except services.InputError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/uncertainty/settings")
def unc_save(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    """Save the values of the budget table: a value equal to the standard one switches the change off."""
    check_csrf(request, form)
    modality = form.get("modality")
    if modality not in ("photon", "electron"):
        raise HTTPException(422, "Неизвестный тип пучка")
    extras = {r["code"] for r in conn.execute("SELECT code FROM uncertainty_settings WHERE modality = %s AND is_extra AND active",
                                              (modality,)).fetchall()}
    changed = 0
    for key in form.keys():
        if not key.startswith("u_"):
            continue
        code = key[2:]
        value = unc_number(form.get(key), "u, %")
        if code in extras:
            conn.execute("UPDATE uncertainty_settings SET u_pct = %s, updated_by = %s, updated_at = now() "
                         "WHERE modality = %s AND code = %s AND is_extra", (value, user["id"], modality, code))
            changed += 1
            continue
        default = unc_number(form.get("d_" + code), "u по умолчанию, %")
        if abs(value - default) < 1e-9:
            conn.execute("UPDATE uncertainty_settings SET active = false, updated_by = %s, updated_at = now() "
                         "WHERE modality = %s AND code = %s AND NOT is_extra AND active", (user["id"], modality, code))
        else:
            conn.execute("""INSERT INTO uncertainty_settings(modality, code, u_pct, updated_by) VALUES (%s, %s, %s, %s)
                            ON CONFLICT (modality, code) DO UPDATE SET u_pct = EXCLUDED.u_pct, active = true,
                            updated_by = EXCLUDED.updated_by, updated_at = now()""", (modality, code, value, user["id"]))
            changed += 1
    audit(conn, user["id"], "uncertainty_settings", "uncertainty", modality, {"changed": changed})
    return RedirectResponse(unc_back(form), status_code=303)


@router.post("/uncertainty/settings/reset")
def unc_reset(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    modality = form.get("modality")
    if modality not in ("photon", "electron"):
        raise HTTPException(422, "Неизвестный тип пучка")
    conn.execute("UPDATE uncertainty_settings SET active = false, updated_by = %s, updated_at = now() "
                 "WHERE modality = %s AND NOT is_extra AND active", (user["id"], modality))
    audit(conn, user["id"], "uncertainty_reset", "uncertainty", modality)
    return RedirectResponse(unc_back(form), status_code=303)


@router.post("/uncertainty/extra")
def unc_extra_add(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    modality, name = form.get("modality"), (form.get("name") or "").strip()
    stage = form.get("stage")
    if modality not in ("photon", "electron") or stage not in ("1", "2"):
        raise HTTPException(422, "Неизвестный тип пучка или этап")
    if len(name) < 3:
        raise HTTPException(422, "Укажите название строки (не короче 3 символов)")
    value = unc_number(form.get("u_new"), "u, %")
    dist = (form.get("dist") or "").strip()
    if dist and dist not in udist.DISTRIBUTIONS:
        raise HTTPException(422, "Неизвестное распределение")
    code = "x" + secrets.token_hex(4)
    conn.execute("""INSERT INTO uncertainty_settings(modality, code, is_extra, stage, name, u_pct, note, updated_by, dist, how)
                    VALUES (%s, %s, true, %s, %s, %s, NULLIF(%s, ''), %s, NULLIF(%s, ''), NULLIF(%s, ''))""",
                 (modality, code, int(stage), name, value, (form.get("note") or "").strip(), user["id"], dist,
                  (form.get("how") or "").strip()[:400]))
    audit(conn, user["id"], "uncertainty_extra_add", "uncertainty", code, {"name": name, "u": value, "dist": dist})
    return RedirectResponse(unc_back(form), status_code=303)


@router.post("/uncertainty/extra/delete")
def unc_extra_delete(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    row = conn.execute("UPDATE uncertainty_settings SET active = false, updated_by = %s, updated_at = now() "
                       "WHERE modality = %s AND code = %s AND is_extra AND active RETURNING code",
                       (user["id"], form.get("modality"), form.get("code"))).fetchone()
    if not row:
        raise HTTPException(404, "Строка не найдена")
    audit(conn, user["id"], "uncertainty_extra_remove", "uncertainty", row["code"])
    return RedirectResponse(unc_back(form), status_code=303)


@router.get("/uncertainty", response_class=HTMLResponse)
def uncertainty_page(request: Request, beam_id: str = "", chamber: str = "", q0: str = "", r50: str = "",
                     tolerance: str = "", observe: str = "", interval: str = "", window: str = "",
                     last_cal: str = "", user=Depends(current_user), conn=Depends(get_db)):
    beams = conn.execute("SELECT b.*, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id "
                         "ORDER BY l.name, b.modality, b.nominal_energy, b.fff").fetchall()
    for b in beams:
        b["label"] = ("γ " if b["modality"] == "photon" else "e⁻ ") + beam_label(b)
    ctx = dict(beams=beams, beam=None, budget=None, advice=None, shares=[], electron_chambers=[], form={})
    if not beam_id:
        return render(request, "uncertainty.html", user, **ctx)
    beam = next((b for b in beams if str(b["id"]) == beam_id), None)
    if not beam:
        raise HTTPException(404, "Пучок не найден")

    pts = trend_points(conn, beam)
    summary = spc.analyse(pts, periods=beam_periods(conn, beam["id"])[0])
    sigma_a = summary.sigma

    if beam["modality"] == "photon":
        budget = uncertainty.photon_budget(sigma_a)
    else:
        names = [c["name"] for c in el_core.load_tables()["chambers"]]
        last = conn.execute("""SELECT s.beam_quality, s.extra, ch.name AS chamber FROM measurement_sessions s
            JOIN calibrations cal ON cal.id = s.calibration_id JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
            JOIN chambers ch ON ch.id = cu.chamber_id
            WHERE s.beam_id = %s AND s.status = 'approved' ORDER BY s.measured_on DESC, s.id DESC LIMIT 1""",
                            (beam["id"],)).fetchone()
        chamber_name = chamber or (last["chamber"] if last and last["chamber"] in names else names[0])
        q0_co60 = (q0 == "co60") if q0 else (bool(last["extra"].get("form", {}).get("q0_is_co60")) if last else True)
        r50w = _opt_float(r50, float(last["extra"].get("r50w") or last["beam_quality"]) if last else 4.0,
                          "R50", 0.5, 12)
        info = next(c for c in el_core.load_tables()["chambers"] if c["name"] == chamber_name)
        budget = uncertainty.electron_budget(info["plane_parallel"], q0_co60, r50w, sigma_a)
        ctx.update(electron_chambers=names, form=dict(chamber=chamber_name, q0="co60" if q0_co60 else "electron",
                                                      r50=f"{r50w:g}", plane_parallel=info["plane_parallel"]))

    last_cal = _opt_date(last_cal)
    form = dict(ctx["form"], tolerance=_opt_float(tolerance, 2.0, "Допуск", 0.5, 10),
                observe=_opt_float(observe, 1.0, "Уровень наблюдения", 0.1, 10),
                interval=int(_opt_float(interval, 12, "Интервал, мес", 1, 60)),
                window=int(_opt_float(window, 12, "Окно, записей", 3, 200)), last_cal=last_cal.isoformat() if last_cal else "")
    advice = uncertainty.recalibration_advice(
        [(p.on, p.deviation_pct) for p in pts], sigma_a, tolerance=form["tolerance"], observe=form["observe"],
        interval_months=form["interval"], last_calibration=last_cal, window=form["window"],
        signals=bool(summary.points and (summary.points[-1].signal or summary.points[-1].cusum_signal)))
    budget = uncertainty.apply_settings(budget, *unc_settings(conn, beam["modality"]))
    shares = budget.contributions()
    ctx.update(can_edit_unc=user["role"] in ("physicist", "admin"), modality=beam["modality"], presets=ulit.PRESETS,
               literature=ulit.LITERATURE, lit_sources=ulit.SOURCES, lit_dist=ulit.LIT_DIST, preset_dist=ulit.PRESET_DIST,
               dist_names={k: v[0] for k, v in udist.DISTRIBUTIONS.items()}, dist_formulas=udist.FORMULAS, dist_rules=udist.SENSITIVITY_RULES, beam=beam, budget=budget, advice=advice, shares=shares, form=form, n_points=summary.n,
               plot={"names": [str(sym(s[0])) for s in shares][::-1], "share": [round(s[3], 2) for s in shares][::-1],
                     "u": [round(s[2], 3) for s in shares][::-1], "kinds": [s[1] for s in shares][::-1]})
    return render(request, "uncertainty.html", user, **ctx)
