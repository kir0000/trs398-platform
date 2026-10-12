"""Uncertainty of the absorbed dose to water (TRS-398 Rev.1 Tables 17 / 24 / 25 and GUM) and the
recalibration advice that the worksheets build from it.

Type B components are the standard values of the IAEA tables as used in the user's worksheets; Type A is the
experimental sigma of the output trend (sigma = MRbar / 1.128). Components are combined in quadrature.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt
from typing import Optional, Sequence

from core import uncertainty_distributions as distributions

K = 2.0                       # coverage factor, ~95 %
DAYS_PER_MONTH = 30.4375
TREND_SIGNIFICANT = 0.05      # %/month


@dataclass
class Component:
    name: str
    kind: str                 # "A" or "B"
    u_pct: float
    note: str = ""
    code: str = ""                      # stable code: settings of a standard component are stored by it
    default_u: Optional[float] = None   # the standard value, when the user has replaced it
    custom: bool = False                # a line added by the user
    dist: str = ""                      # key of core.uncertainty_distributions.DISTRIBUTIONS
    how: str = ""                       # how the value is determined (formula)


@dataclass
class Budget:
    title: str
    stage1_title: str
    stage1: list[Component]
    stage2_title: str
    stage2: list[Component]
    sigma_a: Optional[float] = None

    @staticmethod
    def _rss(items) -> float:
        return sqrt(sum(c.u_pct ** 2 for c in items))

    @property
    def u1(self) -> float:
        return self._rss(self.stage1)

    @property
    def u2(self) -> float:
        return self._rss(self.stage2)

    @property
    def u_type_b(self) -> float:
        """Combined Type B uncertainty (the 'reference' value without journal data)."""
        return sqrt(self.u1 ** 2 + self.u2 ** 2)

    @property
    def uc(self) -> float:
        return sqrt(self.u1 ** 2 + self.u2 ** 2 + (self.sigma_a or 0.0) ** 2)

    @property
    def expanded(self) -> float:
        return K * self.uc

    def contributions(self) -> list[tuple[str, str, float, float]]:
        """(name, kind, u_pct, share of uc^2 in %), largest first. Type A is included when known."""
        items = [(c.name, c.kind, c.u_pct) for c in self.stage1 + self.stage2]
        if self.sigma_a:
            items.append(("Экспериментальное σ по данным журнала", "A", self.sigma_a))
        total = sum(u ** 2 for _, _, u in items) or 1.0
        return sorted(((n, k, u, 100 * u ** 2 / total) for n, k, u in items), key=lambda r: -r[3])


def photon_budget(sigma_a: Optional[float] = None) -> Budget:
    return distributions.decorate(Budget(
        "TRS-398 Rev.1, раздел 6.8 (Табл. 17): фотоны высоких энергий",
        "Этап 1. Поверочная лаборатория",
        [Component("Калибровка вторичного эталона в ДЛПЭ на основе ND,w", "B", 1.25, code="s1_cal_secondary"),
         Component("Долговременная стабильность вторичного эталона", "B", 0.3, code="s1_stab_secondary"),
         Component("Калибровка дозиметра пользователя в поверочной лаборатории на основе ND,w", "B", 0.4, code="s1_cal_user")],
        "Этап 2. Пучок фотонов пользователя",
        [Component("Долговременная стабильность дозиметра пользователя", "B", 0.2, code="s2_stab_user"),
         Component("Установление стандартных условий", "B", 0.3, code="s2_conditions"),
         Component("Показания дозиметра MQ относительно монитора пучка", "B", 0.3, code="s2_reading"),
         Component("Поправка на влияющие величины ki (kTP, kpol, ks, kvol, kelec)", "B", 0.3, code="s2_influence"),
         Component("Коэффициент качества пучка, kQ", "B", 0.6, code="s2_kq")],
        sigma_a))


def electron_budget(plane_parallel: bool, q0_co60: bool, r50: float, sigma_a: Optional[float] = None) -> Budget:
    """Tables 24 (Co-60 calibration) and 25 (calibration in an electron beam, Qint), section 7.10.

    r50 is the R50 of the beam being measured. (The user's worksheet reads a named range R_50 that is empty
    in the file, so its plane-parallel branch always used the R50 < 2 value.)
    """
    if q0_co60:
        stage1 = [Component("Калибровка вторичного эталона в ДЛПЭ на основе ND,w", "B", 1.0, code="s1_cal_secondary"),
                  Component("Долговременная стабильность вторичного эталона", "B", 0.1, code="s1_stab_secondary"),
                  Component("Калибровка дозиметра пользователя в ДЛВЭ на основе ND,w", "B", 0.4, code="s1_cal_user")]
        kq_u = (0.8 if r50 < 2 else 0.7) if plane_parallel else 0.7
        kq_name = "Поправка на качество пучка kQ (расчётные значения, Табл. 24)"
        title1 = "Этап 1. Поверочная лаборатория (калибровка по 60Co)"
    else:
        stage1 = [Component("Калибровка дозиметра пользователя в ДЛПЭ, ND,w", "B", 1.0, code="s1_cal_user_psdl")]
        kq_u = (0.4 if r50 < 2 else 0.2) if plane_parallel else 0.2
        kq_name = "Поправка на качество пучка kQ,Qo (Табл. 25)"
        title1 = "Этап 1. ДЛПЭ (калибровка в электронном пучке)"
    stage2 = [Component("Долговременная стабильность дозиметра пользователя", "B", 0.4 if plane_parallel else 0.2, code="s2_stab_user"),
              Component("Установление стандартных условий", "B", 0.3, code="s2_conditions"),
              Component("Показания дозиметра MQ относительно монитора пучка", "B", 0.3, code="s2_reading"),
              Component("Поправка на влияющие величины ki (kTP, kpol, ks, kelec)", "B", 0.3, code="s2_influence"),
              Component(kq_name, "B", kq_u,
                        "повышена для плоскопараллельной камеры при R50 < 2 г/см²" if plane_parallel and r50 < 2 else "",
                        code="s2_kq"),
              Component("Применимость kQ к комбинации пучок — камера", "B", 0.2 if q0_co60 else 0.1, code="s2_applic")]
    return distributions.decorate(Budget("TRS-398 Rev.1, раздел 7.10 (Табл. 24/25): электроны", title1, stage1,
                                         "Этап 2. Пучок электронов пользователя", stage2, sigma_a), electron=True)


def apply_settings(budget: Budget, overrides: Optional[dict] = None, extras: Sequence[dict] = ()) -> Budget:
    """The user's changes to the standard budget.

    overrides: {component code: u_pct} replaces the value of a standard component (the standard one is kept in
    `default_u`); extras: [{code, name, stage (1 or 2), u_pct, note}] are appended to the stage as Type B lines.
    """
    for c in budget.stage1 + budget.stage2:
        if overrides and c.code in overrides and abs(overrides[c.code] - c.u_pct) > 1e-12:
            c.default_u, c.u_pct = c.u_pct, float(overrides[c.code])
    for x in extras:
        line = Component(x["name"], "B", float(x["u_pct"]), x.get("note") or "", code=x["code"], custom=True,
                         dist=x.get("dist") or "", how=x.get("how") or "")
        (budget.stage1 if int(x["stage"]) == 1 else budget.stage2).append(line)
    return budget


# --------------------------------------------------------------------------- recalibration advice
@dataclass
class Advice:
    last_deviation: Optional[float]
    u_rel: Optional[float]
    verdict: str
    trend_pct_per_month: Optional[float]
    fitted_now: Optional[float]
    months_to_observe: Optional[object]       # float, or a text such as "тренда нет" ("no trend")
    months_to_tolerance: Optional[object]
    months_to_margin: Optional[object]
    planned_date: Optional[date]
    trend_date: Optional[date]
    recommended_date: Optional[date]
    recommendation: str


def _months_to(level: float, sign: float, fitted: float, trend: float):
    if abs(trend) < TREND_SIGNIFICANT:
        return "тренда нет"
    gap = level - sign * fitted
    return "уже достигнуто" if gap <= 0 else gap / abs(trend)


def recalibration_advice(points: Sequence[tuple[date, float]], sigma_a: Optional[float], tolerance: float = 2.0,
                         observe: float = 1.0, interval_months: int = 12, last_calibration: Optional[date] = None,
                         window: int = 12, signals: bool = False, today: Optional[date] = None) -> Advice:
    today = today or date.today()
    pts = sorted(points)
    if last_calibration:
        pts = [p for p in pts if p[0] >= last_calibration]
    if not pts:
        return Advice(None, None, "нет данных", None, None, None, None, None, None, None, None, "Нет данных для оценки")
    last_date, last = pts[-1]
    u_rel = 2 * sqrt(2) * sigma_a if sigma_a else None

    if abs(last) > tolerance:
        verdict = "ДЕЙСТВИЕ: вне допуска"
    elif abs(last) + (u_rel or 0) > tolerance:
        verdict = "ПРЕДУПРЕЖДЕНИЕ: возможен выход за допуск"
    elif abs(last) > observe or signals:
        verdict = "наблюдение"
    else:
        verdict = "норма"

    win = pts[-max(window, 3):]
    trend = fitted = None
    mo_obs = mo_tol = mo_margin = None
    if len(win) >= 3:
        xs = [d.toordinal() for d, _ in win]
        ys = [v for _, v in win]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        fitted = my + slope * (last_date.toordinal() - mx)
        trend = slope * DAYS_PER_MONTH
        sign = 1.0 if slope > 0 else -1.0
        mo_obs = _months_to(observe, sign, fitted, trend)
        mo_tol = _months_to(tolerance, sign, fitted, trend)
        mo_margin = _months_to(tolerance - 2 * (sigma_a or 0.0), sign, fitted, trend)

    planned = None
    if last_calibration:
        m = last_calibration.month - 1 + interval_months
        try:
            planned = last_calibration.replace(year=last_calibration.year + m // 12, month=m % 12 + 1)
        except ValueError:                                           # 29 Feb and similar
            planned = last_calibration.replace(year=last_calibration.year + m // 12, month=m % 12 + 1, day=28)
    trend_date = None
    if isinstance(mo_margin, float):
        trend_date = last_date + timedelta(days=mo_margin * DAYS_PER_MONTH)
    elif mo_margin == "уже достигнуто":
        trend_date = last_date
    cands = [d for d in (planned, trend_date) if d]
    recommended = min(cands) if cands else None

    if verdict.startswith("ДЕЙСТВИЕ"):
        rec = "Калибровать / юстировать выход сейчас"
    elif verdict.startswith("ПРЕДУПРЕЖДЕНИЕ"):
        rec = "Повторить измерение; при подтверждении — юстировать"
    elif recommended is None:
        rec = "Продолжать мониторинг"
    elif recommended <= today:
        rec = "Срок проверки наступил — запланировать проверку или юстировку"
    else:
        rec = f"Продолжать мониторинг; следующая проверка до {recommended:%d.%m.%Y}"
    return Advice(last, u_rel, verdict, trend, fitted, mo_obs, mo_tol, mo_margin, planned, trend_date, recommended, rec)
