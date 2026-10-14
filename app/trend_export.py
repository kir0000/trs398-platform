"""Export of a trend (one beam, one series): the points with the limits and signals, the summary, the baseline periods.
CSV for a quick look and Excel (.xlsx, three sheets) for work. The numbers are exact (not rounded to the screen); the Russian files use
the decimal comma and the semicolon like the Russian Excel, the English ones the point and the comma."""
from __future__ import annotations

import csv
import io
from datetime import date

from app import i18n, xlsx
from core import spc

POINT_HEAD = ["Дата", "Отклонение, %", "MR, %", "Сигнал правил", "CUSUM+", "CUSUM−", "Сигнал CUSUM", "CL, %", "−3σ, %", "+3σ, %",
              "Базовый период №", "До первого базового периода", "Источник", "Протокол №", "Dw(zmax), Гр/MU"]
SOURCES = {"measured": "измерение", "legacy": "журнал (импорт)"}


def point_rows(summary, records: list[dict]) -> list[list]:
    """One row per point of the series; `records` are the rows of the view in the same order (source, protocol, dose)."""
    out = []
    segs = summary.segments
    for i, p in enumerate(summary.points):
        rec = records[i] if i < len(records) else {}
        if segs and 0 <= p.segment < len(segs):
            cl, sigma = segs[p.segment]["cl"], segs[p.segment]["sigma"]
        elif segs:
            cl = sigma = None                                        # before the first baseline period: no limits
        else:
            cl, sigma = summary.cl, summary.sigma
        out.append([p.on, p.deviation_pct, p.mr, p.signal or "", p.cusum_plus, p.cusum_minus, p.cusum_signal or "",
                    cl, None if cl is None or not sigma else cl - 3 * sigma, None if cl is None or not sigma else cl + 3 * sigma,
                    (p.segment + 1) if segs and p.segment >= 0 else "", "да" if p.pre else "",
                    SOURCES.get(rec.get("source"), rec.get("source") or ""), rec.get("protocol_no") or "", rec.get("dw_zmax")])
    return out


def summary_rows(beam_name: str, series: str, summary, user: str, today: date) -> list[list]:
    s = summary
    rows = [["Параметр", "Значение"],
            ["Пучок", beam_name], ["Ряд (опорные условия)", series], ["Записей", s.n], ["Последнее отклонение, %", s.last],
            ["CL, % (среднее)", s.cl], ["σ, % (по MR̄/1,128)", s.sigma], ["MR̄, %", s.mr_bar], ["UCL(MR), %", s.ucl_mr],
            ["Предел наблюдения, %", spc.OBSERVE_PCT], ["Допуск (действие), %", spc.ACTION_PCT], ["Статус", s.status],
            ["Тренд, %/мес", s.trend_pct_per_month], ["Прогноз выхода за допуск", s.forecast_out_of_tolerance],
            ["Порог CUSUM H, % (5σ)", None if not s.sigma else 5 * s.sigma],
            ["Выгружено", today], ["Пользователь", user]]
    return rows


def period_rows(summary) -> list[list]:
    rows = [["Период №", "С", "По", "CL, %", "σ, %", "Точек", "Пределы по самому периоду"]]
    for i, g in enumerate(summary.segments, 1):
        rows.append([i, g["start"], g["end"], g["cl"], g["sigma"], g.get("n"), "да" if g.get("own") else "нет"])
    return rows


def _t(text, lang):
    return i18n.translate_plain(text) if lang == "en" and isinstance(text, str) else text


def translated(rows: list[list], lang: str) -> list[list]:
    return [[_t(c, lang) for c in row] for row in rows]


def to_csv(rows: list[list], lang: str) -> bytes:
    """The points as a CSV: ';' and the decimal comma for Russian, ',' and the point for English; the BOM lets Excel read the letters."""
    sep = ";" if lang == "ru" else ","
    out = io.StringIO()
    w = csv.writer(out, delimiter=sep, lineterminator="\r\n")
    for row in translated(rows, lang):
        cells = []
        for v in row:
            if isinstance(v, float):
                v = f"{v:.6g}" if lang != "ru" else f"{v:.6g}".replace(".", ",")
            elif isinstance(v, date):
                v = v.strftime("%d.%m.%Y")
            elif v is None:
                v = ""
            cells.append(v)
        w.writerow(cells)
    return ("﻿" + out.getvalue()).encode("utf-8")


def to_xlsx(sheets: list[tuple[str, list[list]]], lang: str) -> bytes:
    return xlsx.write([(_t(name, lang), translated(rows, lang)) for name, rows in sheets])
