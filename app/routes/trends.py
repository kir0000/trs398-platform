"""Trends of a beam (chart, export), the comparison of the energies of a linac and the baseline periods."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import compare_export as compare_export_module
from app import trend_export
from app.chart import control_chart
from app.common import beam_label, beam_periods, key_label, trend_keys, trend_points
from app.db import audit, get_db
from app.web import check_csrf, current_lang, current_user, form_data, int_or_404, render, require
from core import compare, spc

router = APIRouter()


def plot_data(summary):
    """Plain data for the interactive (Plotly) trend chart; the server-side SVG stays as the fallback."""
    return {
        "x": [p.on.isoformat() for p in summary.points],
        "y": [round(p.deviation_pct, 4) for p in summary.points],
        "signal": [p.signal or "" for p in summary.points],
        "cusum": [p.cusum_signal or "" for p in summary.points],
        "cusum_plus": [round(p.cusum_plus, 4) for p in summary.points], "cusum_minus": [round(p.cusum_minus, 4) for p in summary.points],
        "h": round(5 * summary.sigma, 4) if summary.sigma else None,
        "pre": [bool(p.pre) for p in summary.points], "segment": [p.segment for p in summary.points],
        "segments": [{"start": g["start"].isoformat(), "end": g["end"].isoformat() if g["end"] else None, "cl": g["cl"], "sigma": g["sigma"],
                      "h": round(5 * g["sigma"], 4) if g["sigma"] else None} for g in summary.segments],
        "cl": summary.cl, "sigma": summary.sigma,
        "tolerance": spc.ACTION_PCT, "observe": spc.OBSERVE_PCT,
    }


@router.get("/trends", response_class=HTMLResponse)
def trends(request: Request, beam_id: str = "", cond: str = "", user=Depends(current_user), conn=Depends(get_db)):
    beams = conn.execute("SELECT b.*, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id "
                         "ORDER BY l.name, b.modality, b.nominal_energy, b.fff").fetchall()
    for b in beams:
        b["label"] = ("γ " if b["modality"] == "photon" else "e⁻ ") + beam_label(b)
    ctx = dict(beams=beams, beam=None, summary=None, chart="", period_rows=[], baseline_fixed=False, signals=[])
    if beam_id:
        beam = next((b for b in beams if str(b["id"]) == beam_id), None)
        if not beam:
            raise HTTPException(404, "Пучок не найден")
        keys = trend_keys(conn, beam)
        key = cond if cond in [k["ref_key"] for k in keys] else (keys[0]["ref_key"] if keys else None)
        pts = trend_points(conn, beam, key)
        periods, period_rows = beam_periods(conn, beam["id"])
        summary = spc.analyse(pts, periods=periods)
        ctx.update(plot=plot_data(summary), beam=beam, summary=summary, chart=control_chart(summary), period_rows=period_rows,
                   baseline_fixed=bool(summary.segments), today=date.today(),
                   series=[dict(key=k["ref_key"], label=key_label(k["ref_key"]), n=k["n"], last=k["last_on"]) for k in keys], series_key=key,
                   signals=[p for p in summary.points if p.signal or p.cusum_signal][-15:])
    return render(request, "trends.html", user, **ctx)


@router.get("/trends/export")
def trends_export(request: Request, beam_id: str, cond: str = "", fmt: str = "xlsx", user=Depends(current_user), conn=Depends(get_db)):
    """The series of one beam as a CSV or an Excel file: the points with the limits and the signals, the summary, the baseline periods."""
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(422, "Формат: csv или xlsx")
    beam = conn.execute("SELECT b.*, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id WHERE b.id = %s",
                        (int_or_404(beam_id, "Пучок"),)).fetchone()
    if not beam:
        raise HTTPException(404, "Пучок не найден")
    keys = trend_keys(conn, beam)
    key = cond if cond in [k["ref_key"] for k in keys] else (keys[0]["ref_key"] if keys else None)
    periods, _rows = beam_periods(conn, beam["id"])
    summary = spc.analyse(trend_points(conn, beam, key), periods=periods)
    if summary.n == 0:
        raise HTTPException(404, "Для этого пучка нет данных для выгрузки")
    records = conn.execute("""SELECT t.source, t.record_id, t.dw_zmax, s.protocol_no FROM v_trend t
        LEFT JOIN measurement_sessions s ON t.source = 'measured' AND s.id = t.record_id
        WHERE t.linac = %s AND t.modality = %s AND t.nominal_energy = %s AND t.fff = %s AND t.ref_key IS NOT DISTINCT FROM %s
        ORDER BY t.measured_on, t.source, t.record_id""", (beam["linac"], beam["modality"], beam["nominal_energy"], beam["fff"], key)).fetchall()
    lang = current_lang(request)
    name = f"{beam['linac']}, {beam_label(beam)}"
    points = [trend_export.POINT_HEAD] + trend_export.point_rows(summary, records)
    if fmt == "csv":
        body, media, ext = trend_export.to_csv(points, lang), "text/csv; charset=utf-8", "csv"
    else:
        sheets = [("Данные", points), ("Сводка", trend_export.summary_rows(name, key_label(key), summary, user["full_name"], date.today())),
                  ("Базовые периоды", trend_export.period_rows(summary))]
        body = trend_export.to_xlsx(sheets, lang)
        media, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    audit(conn, user["id"], "trends_export", "beams", beam["id"], {"format": ext, "rows": summary.n, "series": key_label(key)})
    from urllib.parse import quote
    pretty = quote(f"trend {name}.{ext}".replace(",", ""))
    return Response(body, media_type=media, headers={"Content-Disposition": f"attachment; filename=\"trend.{ext}\"; filename*=UTF-8''{pretty}"})


COMPARE_MODALITIES = {"all": "фотоны и электроны", "photon": "только фотоны", "electron": "только электроны"}
COMPARE_PERIODS = {"": "весь период", "24": "последние 24 мес", "12": "последние 12 мес", "6": "последние 6 мес"}


def compare_data(conn, linac: dict, modality: str, months: str) -> dict | None:
    """Everything the comparison of the energies of one linac shows (the page and the export use the same numbers); None: no data."""
    since = None
    if months:
        today = date.today()
        total = today.year * 12 + today.month - 1 - int(months)
        since = date(total // 12, total % 12 + 1, 1)

    beams = conn.execute("""SELECT b.id, b.modality, b.nominal_energy, b.fff, l.name AS linac FROM beams b
                            JOIN linacs l ON l.id = b.linac_id WHERE l.id = %s ORDER BY b.modality, b.nominal_energy, b.fff""",
                         (linac["id"],)).fetchall()
    series, baselines = {}, {}
    for b in beams:
        if modality != "all" and b["modality"] != modality:
            continue
        pts = trend_points(conn, b)
        if since:
            pts = [p for p in pts if p.on >= since]
        if not pts:
            continue
        label = f"{'γ' if b['modality'] == 'photon' else 'e⁻'} {b['nominal_energy']:g} {'MV' if b['modality'] == 'photon' else 'MeV'}" \
                f"{' FFF' if b['fff'] else ''}"
        series[label] = pts
        periods = beam_periods(conn, b["id"])[0]
        if periods:
            baselines[label] = periods
    if not series:
        return None
    mths, matrix = compare.align(series)
    common = compare.common_mode(mths, matrix)
    corr_labels, corr = compare.correlations(mths, matrix)
    return dict(series=series, months=mths, matrix=matrix, common=common, corr_labels=corr_labels, corr=corr,
                summaries=[compare.beam_summary(label, pts, baselines.get(label)) for label, pts in series.items()],
                hints=compare.interpretation(common, corr_labels, corr))


def compare_linac(conn, linac_id: str):
    """The linac of the comparison: the chosen one, else the one with the most beams; None when there are no linacs."""
    linacs = conn.execute("""SELECT l.id, l.name, (SELECT count(DISTINCT t.modality || '|' || t.nominal_energy || '|' || t.fff) FROM v_trend t
                             WHERE t.linac = l.name) AS n_beams FROM linacs l ORDER BY l.name""").fetchall()
    if not linacs:
        return linacs, None
    linac = next((l for l in linacs if str(l["id"]) == linac_id), None) if linac_id else max(linacs, key=lambda l: l["n_beams"])
    if linac is None:
        raise HTTPException(404, "Аппарат не найден")
    return linacs, linac


@router.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request, linac_id: str = "", modality: str = "all", months: str = "",
                 user=Depends(current_user), conn=Depends(get_db)):
    """Trends of several energies of one linac side by side, with a search for a common cause."""
    if modality not in COMPARE_MODALITIES or months not in COMPARE_PERIODS:
        raise HTTPException(422, "Неверные параметры сравнения")
    linacs, linac = compare_linac(conn, linac_id)
    ctx = dict(linacs=linacs, linac=None, modality=modality, months=months, modalities=COMPARE_MODALITIES,
               periods=COMPARE_PERIODS, summaries=[], hints=[], flagged=[], corr_labels=[], plot={},
               min_beams=compare.MIN_BEAMS, shift=str(compare.SHIFT_PCT).replace(".", ","))
    if not linacs:
        return render(request, "compare.html", user, **ctx)
    ctx["linac"] = linac
    data = compare_data(conn, linac, modality, months)
    if data is None:
        return render(request, "compare.html", user, **ctx)
    series, matrix, common = data["series"], data["matrix"], data["common"]
    ctx.update(
        summaries=data["summaries"], hints=data["hints"], flagged=[c for c in common if c.flagged], corr_labels=data["corr_labels"],
        plot={"series": [{"label": label, "x": [p.on.isoformat() for p in pts], "y": [round(p.deviation_pct, 3) for p in pts]}
                         for label, pts in series.items()],
              "common": {"x": [c.month + "-15" for c in common], "y": [round(c.mean, 3) for c in common]},
              "months": data["months"], "labels": list(matrix), "matrix": [[None if v is None else round(v, 3) for v in row] for row in matrix.values()],
              "corr_labels": data["corr_labels"], "corr": [[None if v is None else round(v, 3) for v in row] for row in data["corr"]]})
    return render(request, "compare.html", user, **ctx)


@router.get("/compare/export")
def compare_export(request: Request, linac_id: str = "", modality: str = "all", months: str = "", fmt: str = "xlsx",
                   user=Depends(current_user), conn=Depends(get_db)):
    """The comparison of the energies of a linac as a CSV (the table of the states) or an Excel file (four sheets)."""
    if modality not in COMPARE_MODALITIES or months not in COMPARE_PERIODS:
        raise HTTPException(422, "Неверные параметры сравнения")
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(422, "Формат: csv или xlsx")
    _linacs, linac = compare_linac(conn, linac_id)
    data = compare_data(conn, linac, modality, months) if linac else None
    if data is None:
        raise HTTPException(404, "Для этого аппарата и периода нет данных для выгрузки")
    lang = current_lang(request)
    status = compare_export_module.status_rows(data["summaries"])
    if fmt == "csv":
        body, media, ext = trend_export.to_csv(status, lang), "text/csv; charset=utf-8", "csv"
    else:
        info = compare_export_module.parameter_rows(linac["name"], COMPARE_MODALITIES[modality], COMPARE_PERIODS[months], user["full_name"], date.today())
        sheets = [("Параметры", info), ("Состояние", status), ("По месяцам", compare_export_module.month_rows(data)),
                  ("Корреляции", compare_export_module.correlation_rows(data)), ("Выводы", compare_export_module.hint_rows(data))]
        body = trend_export.to_xlsx(sheets, lang)
        media, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    audit(conn, user["id"], "compare_export", "linacs", linac["id"], {"format": ext, "rows": len(data["summaries"]), "series": COMPARE_PERIODS[months]})
    from urllib.parse import quote
    pretty = quote(f"compare {linac['name']}.{ext}")
    return Response(body, media_type=media, headers={"Content-Disposition": f"attachment; filename=\"compare.{ext}\"; filename*=UTF-8''{pretty}"})


@router.post("/trends/baseline")
def set_baseline(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    beam_id = int_or_404(form.get("beam_id"), "Пучок")
    try:
        d1, d2 = date.fromisoformat(form.get("from_date") or ""), date.fromisoformat(form.get("to_date") or "")
    except ValueError:
        raise HTTPException(422, "Укажите даты начала и конца базового периода") from None
    if d2 < d1:
        raise HTTPException(422, "Конец периода раньше начала")
    conn.execute("""INSERT INTO spc_baseline(beam_id, from_date, to_date, set_by) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (beam_id, from_date) DO UPDATE SET to_date = EXCLUDED.to_date,
                    set_by = EXCLUDED.set_by, set_at = now()""", (beam_id, d1, d2, user["id"]))
    audit(conn, user["id"], "set_baseline", "spc_baseline", beam_id, {"from": str(d1), "to": str(d2)})
    return RedirectResponse(f"/trends?beam_id={beam_id}", status_code=303)


@router.post("/trends/baseline/delete")
def delete_baseline(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    row = conn.execute("DELETE FROM spc_baseline WHERE id = %s RETURNING beam_id, from_date, to_date",
                       (int_or_404(form.get("id"), "Период"),)).fetchone()
    if not row:
        raise HTTPException(404, "Базовый период не найден")
    audit(conn, user["id"], "delete_baseline", "spc_baseline", row["beam_id"], {"from": str(row["from_date"]), "to": str(row["to_date"])})
    return RedirectResponse(f"/trends?beam_id={row['beam_id']}", status_code=303)
