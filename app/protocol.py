"""Protocol content, laid out like the user's worksheet, sheet "Calculation" («Расчёт»).

build() turns a measurement (session row + results row) into a flat dict `v` of display values and flags;
templates/protocol.html places them in the worksheet's rows and cell colours (yellow = entered,
cyan = calculated, green = key measured values). Values that were not entered are shown as an em dash.
"""
from __future__ import annotations

from core import electron as el
from core import photon as ph
from core import spc, uncertainty
from core import uncertainty_distributions as udist
from core import uncertainty_text as ut

DASH = "—"
SIGN = ("+", "−", "-")


def _mean(vals):
    vals = [float(x) for x in vals or []]           # PostgreSQL numeric arrives as Decimal
    return sum(vals) / len(vals) if vals else None


def f(v, nd=5, unit=""):
    if v is None or v == "":
        return DASH
    try:
        s = f"{float(v):.{nd}f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(v)
    return f"{s} {unit}".strip()


def g(v, unit=""):
    if v is None or v == "":
        return DASH
    try:
        s = f"{float(v):g}".replace(".", ",")
    except (TypeError, ValueError):
        return str(v)
    return f"{s} {unit}".strip()


def sci(v, nd=4):
    """1,2355E-01 as on the worksheet."""
    return DASH if v is None else f"{float(v):.{nd}E}".replace(".", ",")


def t(v):
    return DASH if v in (None, "") else str(v)


def _chamber_info(modality, name):
    tables = ph.load_tables() if modality == "photon" else el.load_tables()
    for c in tables["chambers"]:
        if c["name"] == name:
            return c
    return {}


def _polarity(text):
    text = (text or "").strip()
    return {"plus": "+" in text, "minus": any(c in text for c in SIGN[1:])}


def _num(text, default=None):
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _months(v):
    if v is None:
        return DASH
    return v if isinstance(v, str) else f"{v:.1f}".replace(".", ",") + " мес"


def _date(d):
    return d.strftime("%d.%m.%Y") if d else DASH


def uncertainty_block(s: dict, history, periods=None, tolerance=2.0, observe=1.0, interval=12, window=12, settings=None):
    """Content of the protocol appendix "Uncertainty estimate" (Russian title «Оценка неопределённости»; basis: the electron worksheet's analysis sheet).

    history: [(date, deviation %)] of the beam up to and including this measurement; periods: optional baseline periods [(from, to)].
    """
    photon = s["modality"] == "photon"
    ex = s.get("extra") or {}
    form = ex.get("form", {})
    texts = ut.PHOTON if photon else ut.ELECTRON
    summary = spc.analyse([spc.Point(d, v) for d, v in history], periods=periods)
    sigma_a = summary.sigma
    if photon:
        budget = uncertainty.photon_budget(sigma_a)
        path = "по ⁶⁰Co, расчётный kQ (Табл. 17)" if s.get("cal_q0") in (None, "Co-60") else f"Q0: {s.get('cal_q0')}"
        config = [("Камера", f"{s['chamber']}, SN {s['serial_no']}"),
                  ("Качество пучка", f"TPR20,10 = {f(s['beam_quality'], 4)}"), ("Путь калибровки ND,w", path)]
    else:
        info = _chamber_info("electron", s["chamber"])
        pp = bool(info.get("plane_parallel"))
        q0_co60 = bool(form.get("q0_is_co60"))
        r50 = float(ex.get("r50w") or s["beam_quality"])
        budget = uncertainty.electron_budget(pp, q0_co60, r50, sigma_a)
        config = [("Камера", f"{s['chamber']}, SN {s['serial_no']}"),
                  ("Тип камеры", "плоскопараллельная (R50 ≥ 2 г/см²)" if pp else "цилиндрическая (R50 ≥ 3 г/см²)"),
                  ("Путь калибровки ND,w", "по ⁶⁰Co, расчётный kQ,Qo (Табл. 24)" if q0_co60
                   else "в пучке электронов, Qint (Табл. 25)"),
                  ("R50 текущего пучка", f"{f(r50, 3)} г/см²")]

    if settings:                                          # the user's changes of the Type B values and added lines
        uncertainty.apply_settings(budget, *settings)
    changed = sum(1 for c in budget.stage1 + budget.stage2 if c.custom or c.default_u is not None)
    if changed:
        config.append(("Значения Типа B", f"изменены пользователем: {changed}"))

    def rows(items, stage_no):
        out = []
        for i, c in enumerate(items):
            ref = texts["refs"].get(f"stage{stage_no}_{i + 1}", "") if not c.custom else ""
            note = ref or c.note
            if c.custom:
                note = "добавлено пользователем" + (f": {c.note}" if c.note else "")
            elif c.default_u is not None:
                note = f"изменено, по умолчанию {f(c.default_u, 2)}" + (f"; {note}" if note else "")
            dist = udist.DISTRIBUTIONS.get(c.dist, ('',))[0]
            out.append((c.name, c.kind, f(c.u_pct, 2), note, dist, c.how))
        return out

    last_signal = summary.points[-1] if summary.points else None
    signals = bool(last_signal and (last_signal.signal or last_signal.cusum_signal))
    adv = uncertainty.recalibration_advice(history, sigma_a, tolerance, observe, interval, None, window, signals)
    sig_text = DASH
    if last_signal is not None:
        sig_text = "нет" if not signals else "SPC: " + (last_signal.signal or "нет") + "; CUSUM: " + (last_signal.cusum_signal or "нет")

    decision = None
    if adv.verdict != "нет данных":
        dn = ut.DECISION_NOTES
        decision = {
            "intro": ut.DECISION_INTRO, "limits": ut.DECISION_LIMITS,
            "params": [("Допуск на отклонение выхода (уровень действия), ±T", f"{g(tolerance)} %", dn["tolerance"]),
                       ("Уровень наблюдения, ±", f"{g(observe)} %", dn["observe"]),
                       ("Плановый интервал между калибровками", f"{interval} мес", dn["interval"]),
                       ("Дата последней калибровки / юстировки", DASH, "Не задана: окно тренда — последние N записей."),
                       ("Окно оценки тренда, последних записей", str(window), dn["window"])],
            "state": [("Последнее отклонение от номинала", f"{f(adv.last_deviation, 2)} %", "Текущая запись."),
                      ("Сигналы SPC / CUSUM", sig_text, dn["signals"]),
                      ("U_отн — расширенная неопределённость отклонения от базовой линии (k = 2)",
                       f"{f(adv.u_rel, 2)} %" if adv.u_rel else DASH, dn["u_rel"]),
                      ("Для сравнения: расширенная абсолютная неопределённость U (k = 2)", f"{f(budget.expanded, 2)} %", dn["u_abs"]),
                      ("Вердикт по последнему измерению", adv.verdict, dn["verdict"])],
            "forecast": [("Тренд, %/мес", f(adv.trend_pct_per_month, 3) if adv.trend_pct_per_month is not None else "нет данных", dn["trend"]),
                         ("Отклонение по линии тренда на последнюю дату", f"{f(adv.fitted_now, 3)} %" if adv.fitted_now is not None else DASH, dn["fitted"]),
                         ("Месяцев до уровня наблюдения", _months(adv.months_to_observe), dn["m_obs"]),
                         ("Месяцев до допуска ±T (центральная линия тренда)", _months(adv.months_to_tolerance), dn["m_tol"]),
                         ("Месяцев до допуска с запасом T − 2σ", _months(adv.months_to_margin), dn["m_margin"]),
                         ("Плановая дата следующей калибровки (по интервалу)", _date(adv.planned_date), dn["planned"]),
                         ("Дата достижения T − 2σ по тренду", _date(adv.trend_date), dn["trend_date"]),
                         ("Рекомендуемая дата следующей калибровки / проверки", _date(adv.recommended_date), dn["recommended"]),
                         ("Рекомендация", adv.recommendation, dn["recommendation"])],
        }
    return {
        "title": texts["title"], "subtitle": texts["subtitle"], "config": config,
        "stage1_title": budget.stage1_title, "stage1": rows(budget.stage1, 1), "u1": f(budget.u1, 2),
        "stage2_title": budget.stage2_title, "stage2": rows(budget.stage2, 2), "u2": f(budget.u2, 2),
        "type_a_text": texts["type_a"], "sigma_a": f(sigma_a, 2) if sigma_a else DASH, "n_points": summary.n,
        "combine": texts["combine"], "uc": f(budget.uc, 2), "U": f(budget.expanded, 2),
        "reference_label": texts["reference_label"], "reference": f(budget.u_type_b, 2),
        "reference_note": texts["reference_note"], "context": texts["context"],
        "definitions": [d.format(tables=texts["tables"]) for d in ut.DEFINITIONS],
        "notes_title": texts["notes_title"], "notes": texts["notes"], "source": texts["source"],
        "decision": decision,
    }


def _series_mean(text):
    """Mean of a series typed as '24,36 24,36 24,36' (None when empty)."""
    vals = []
    for part in str(text or "").replace(";", " ").split():
        try:
            vals.append(float(part.replace(",", ".")))
        except ValueError:
            return None
    return sum(vals) / len(vals) if vals else None


def _iso_to_ru(text):
    try:
        y, m, d = str(text).split("-")
        return f"{d}.{m}.{y}"
    except ValueError:
        return DASH


def build(s: dict, res: dict, history=None, periods=None, unc_settings=None) -> dict:
    photon = s["modality"] == "photon"
    ex = s.get("extra") or {}
    form = ex.get("form", {})
    ch = _chamber_info(s["modality"], s["chamber"])
    m1, m2 = _mean(s["m1_readings"]), _mean(s["m2_readings"])
    mp, mm = _mean(s.get("m_plus_readings")), _mean(s.get("m_minus_readings"))
    m1_ks = _series_mean(form.get("m1_v1")) or m1                          # (iv) M1 at V1 from the reference determination
    mu, v1, v2 = float(s["mu"]), float(s["v1"]), float(s["v2"])
    pulsed_scanned = bool(form.get("pulsed_scanned"))
    a0, a1, a2 = ph.ks_coefficients(v1 / v2, pulsed_scanned)
    zref = (_num(form.get("zref"), 10.0) if photon else ex.get("zref"))
    ref_dist = _num(form.get("ref_distance"), 100.0) if photon else 100.0
    q0_co60 = (s.get("cal_q0") in (None, "Co-60")) if photon else bool(form.get("q0_is_co60"))
    unit_e = "МВ" if photon else "МэВ"
    energy = f"{g(s['nominal_energy'])}" + (" FFF" if s["fff"] else "")
    cal_pol, user_pol = _polarity(form.get("polarity_cal")), _polarity(form.get("polarity_user"))
    t0_default = 22 if photon else 20
    sad_exp = res["dw_zmax"] is None                                  # SAD with the planning-system value: the dose at the reference point
    dw100 = float(res["dw_zref"] if sad_exp else res["dw_zmax"]) * 100
    ref_mu = 200 if photon else 100
    sad = photon and s["geometry"] == "SAD"

    v = {
        "photon": photon,
        "doc_name": f"TRS-398 Rev.1 {'фотоны' if photon else 'электроны'} · протокол №{s.get('protocol_no') or s['id']}",
        "title": "Рабочий лист для определения поглощенной дозы в воде",
        "subtitle": ("в высокоэнергетических пучках фотонов" if photon else "в пучках электронов высоких энергий")
                    + " по формализму TRS-398 Rev.1 (МАГАТЭ, 2024)",
        # --- 1
        "linac": t(s["linac"]), "city": t(form.get("city")),
        "linac_model": t(" ".join(x for x in (s.get("linac_model") or "", ("SN " + s["linac_serial"]) if s.get("linac_serial") else "") if x)
                         or form.get("linac_model")),
        "energy": energy, "energy_unit": unit_e, "dose_rate": g(form.get("dose_rate")),
        "filter": "БВФ (без фильтра)" if s["fff"] else "СВФ (с фильтром)",
        "phantom": t(form.get("phantom") or "водный"),
        "win_m": t(form.get("window_material")), "win_t": g(form.get("window_thickness")),
        "plastic": t(form.get("phantom") if form.get("phantom") and not str(form.get("phantom")).lower().startswith("вод") else None),
        "field": t(form.get("field_size") or ("10 х 10" if photon else None)),
        "sad": sad, "ssd": not sad, "zref": f(zref, 1 if photon else 3),
        "ref_dist": g(ref_dist), "pdd10": f(form.get("pdd10"), 1) if form.get("pdd10") else DASH,
        "pdd20": f(form.get("pdd20"), 1) if form.get("pdd20") else DASH,
        "tpr": f(s["beam_quality"], 3),
        "q_source": ("введено" if form.get("tpr") else "по PDD" if form.get("pdd10") else ""),
        "r50_measured": f(s["beam_quality"], 3), "r50w": f(ex.get("r50w"), 3), "c_pl": g(form.get("c_pl") or 1),
        "h_pl": g(form.get("h_pl") or 1),
        # --- 2
        "chamber": t(s["chamber"]), "serial": t(s["serial_no"]),
        "wall_material": t(ch.get("wall_material")), "wall_thickness": g(ch.get("wall_thickness")),
        "nd_w": g(s["nd_w"]), "q0_co60": q0_co60, "q0_photon": photon and not q0_co60,
        "cal_depth": g(form.get("cal_depth")), "q0_tpr": DASH,
        "p0": g(form.get("p0") or 101.325), "t0": g(form.get("t0") or t0_default), "cal_rh": g(form.get("cal_rh")),
        "cal_v1": g(s.get("cal_voltage") if s.get("cal_voltage") is not None else s["v1"]),
        "cal_pol_plus": cal_pol["plus"], "cal_pol_minus": cal_pol["minus"],
        "user_pol_plus": user_pol["plus"], "user_pol_minus": user_pol["minus"],
        "r50_q0": g(form.get("r50_q0")),
        "lab": t(s.get("cal_lab")), "cal_date": s["calibrated_on"].strftime("%d.%m.%Y") if s.get("calibrated_on") else DASH,
        "el_model": t(s.get("el_model") or form.get("electrometer_model")), "el_sn": t(s.get("el_sn") or form.get("electrometer_sn")),
        "kelec_sep": bool(form.get("kelec_separate") or s.get("kelec_separate")),
        "kelec_lab": t(form.get("kelec_lab")), "kelec_date": _iso_to_ru(form["kelec_date"]) if form.get("kelec_date") else DASH,
        "cal_pol_corrected": bool(form.get("cal_pol_corrected")),
        "el_range": t(form.get("electrometer_range")),
        # --- 3
        "rdg": f(m1, 4), "mu": g(mu), "m_per_mu": f(m1 / mu, 4),
        "pressure": f(s["pressure_kpa"], 2), "temp": f(s["temp_c"], 1), "rh": g(s.get("humidity_pct")),
        "k_tp": f(res["k_tp"], 3), "k_elec": f(res["k_elec"], 4),
        "m_plus": f(mp, 2) if mp is not None else DASH, "m_minus": f(mm, 2) if mm is not None else DASH,
        "k_pol": f(res["k_pol"], 4),
        "v1": g(v1), "v2": g(v2), "m1": f(m1_ks, 3), "m2": f(m2, 2),
        "pulsed": not pulsed_scanned, "scanned": pulsed_scanned,
        "v_ratio": f(v1 / v2, 4), "m_ratio": f(m1_ks / m2, 3),
        "a0": f(a0, 4), "a1": f(a1, 4), "a2": f(a2, 4), "k_s": f(res["k_s"], 4),
        "rid": g(ref_dist + zref) if photon else DASH, "cavity": g(ch.get("cavity_length_cm")),
        "k_vol": f(res["k_vol"], 4), "m_q": sci(res["m_corrected"]),
        "ks_minus_1": f(res["k_s"] - 1, 3), "ks_alt": f((m1_ks / m2 - 1) / (v1 / v2 - 1), 3),
        # --- 4 and 5
        "k_q": f(res["k_q"], 4),
        "kq_table16": photon, "kq_table20": (not photon) and q0_co60, "kq_table21": (not photon) and not q0_co60,
        "dw_zref": f(res["dw_zref"], 6), "zmax": g(form.get("zmax")),
        "pdd_zref": f(s.get("pdd_zref"), 2), "tmr_zref": f(s.get("tmr_zref"), 4),
        "dw_zmax_ssd": f(res["dw_zmax"], 6) if not sad else DASH,
        "dw_zmax_sad": f(res["dw_zmax"], 6) if sad else DASH,
        "dw_zmax": f(res["dw_zmax"], 6), "deviation": f(res["deviation_pct"], 2),
        # --- note block
        "check_before": f(dw100, 4), "check_ideal": f(form.get("exp_cgy_mu"), 4) if sad_exp else "1", "check_pct": f(float(res["deviation_pct"]), 3),
        "check_standard": f(dw100 * ref_mu, 2), "ref_mu": ref_mu,
        "kq_note": "определение kQ,Q0 по " + ("TPR20,10 с линейной интерполяцией" if photon else
                                              "R50,w кубическим сплайном"),
        "tables_note": ("Table16" if photon else "Table20/21") + ", TRS398 Rev.1 https://doi.org/10.61092/iaea.ve7q-y94k",
        "formula_version": res["formula_version"], "tables_version": res["tables_version"],
    }
    v["unc"] = uncertainty_block(s, history, periods, settings=unc_settings) if history else None
    return v
