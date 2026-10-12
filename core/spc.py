"""Statistical process control for the output trend (I-MR chart rules and CUSUM).

Mirrors the worksheet sheets "Журнал" and "Тренд": control limits come from the average moving range
(sigma = MRbar / 1.128), signals are the three Western Electric rules used in the worksheet, CUSUM uses
k = 0.5 sigma and H = 5 sigma. Deviations are percent from the nominal 1 cGy/MU.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

D2 = 1.128             # I-MR constant for n = 2
D4 = 3.267             # UCL(MR) = D4 * MRbar
ACTION_PCT = 2.0
OBSERVE_PCT = 1.0
DAYS_PER_MONTH = 30.4375


@dataclass
class Point:
    on: date
    deviation_pct: float


@dataclass
class SpcPoint:
    on: date
    deviation_pct: float
    mr: Optional[float]
    signal: Optional[str]
    cusum_plus: float
    cusum_minus: float
    cusum_signal: Optional[str]
    pre: bool = False                 # before the first baseline period: shown, but no limits and no signals
    segment: int = 0                  # index of the baseline period the point belongs to (-1: before the first one)


@dataclass
class SpcSummary:
    n: int
    last: Optional[float]
    cl: Optional[float]
    mr_bar: Optional[float]
    sigma: Optional[float]
    ucl_mr: Optional[float]
    status: str
    trend_pct_per_month: Optional[float]
    forecast_out_of_tolerance: Optional[date]
    points: list[SpcPoint]
    segments: list[dict] = field(default_factory=list)       # baseline periods: start, end, CL, sigma, n, own (limits from the segment itself)


def _slope_intercept(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return slope, my - slope * mx


def status_for(deviation_pct: float) -> str:
    if abs(deviation_pct) > ACTION_PCT:
        return "ДЕЙСТВИЕ: |отклонение| > 2 %"
    if abs(deviation_pct) > OBSERVE_PCT:
        return "наблюдение: |отклонение| > 1 %"
    return "норма"


def analyse(points: Sequence[Point], baseline: Optional[tuple[float, float]] = None,
            periods: Optional[Sequence[tuple[date, date]]] = None) -> SpcSummary:
    """Analyse points ordered by date.

    baseline: optional (CL, sigma) fixed from a reference period; by default CL and sigma are computed from
    all points, as the worksheet does (so they shift with every new record).

    periods: baseline periods [(from, to)]. A period starts a segment of the series (up to the start of the next period):
    CL and sigma come from the points of the period, the rules and the CUSUM of the segment start from zero at its first
    point. Points before the first period are kept for the picture but carry no limits and no signals.
    """
    if periods:
        return _analyse_periods(sorted(points, key=lambda p: p.on), periods)
    pts = sorted(points, key=lambda p: p.on)
    n = len(pts)
    if n == 0:
        return SpcSummary(0, None, None, None, None, None, "нет данных", None, None, [])
    xs = [p.deviation_pct for p in pts]
    mrs = [None] + [abs(xs[i] - xs[i - 1]) for i in range(1, n)]
    valid_mr = [m for m in mrs if m is not None]

    if baseline is not None:
        cl, sigma = baseline
        mr_bar = sigma * D2
    else:
        cl = sum(xs) / n if n >= 2 else None
        mr_bar = sum(valid_mr) / len(valid_mr) if valid_mr else None
        sigma = mr_bar / D2 if mr_bar is not None else None
    ucl_mr = D4 * mr_bar if mr_bar is not None else None

    out: list[SpcPoint] = []
    cp = cm = 0.0
    for i, p in enumerate(pts):
        signal = None
        csig = None
        if cl is not None and sigma:
            x = p.deviation_pct
            rec = i + 1                                   # record number, as the worksheet's column J
            window3 = xs[max(0, i - 2): i + 1]
            window8 = xs[max(0, i - 7): i + 1]
            if abs(x - cl) > 3 * sigma:
                signal = "за 3σ"
            elif rec >= 3 and (sum(v > cl + 2 * sigma for v in window3) >= 2
                               or sum(v < cl - 2 * sigma for v in window3) >= 2):
                signal = "2 из 3 за 2σ"
            elif rec >= 8 and (all(v > cl for v in window8) or all(v < cl for v in window8)):
                signal = "8 подряд по одну сторону"
            k, h = 0.5 * sigma, 5 * sigma
            cp = max(0.0, cp + (x - cl) - k)
            cm = min(0.0, cm + (x - cl) + k)
            if cp > h:
                csig = "CUSUM+: сдвиг вверх"
            elif cm < -h:
                csig = "CUSUM−: сдвиг вниз"
        out.append(SpcPoint(p.on, p.deviation_pct, mrs[i], signal, cp, cm, csig))

    trend = forecast = None
    if n >= 3:
        days = [p.on.toordinal() for p in pts]
        slope, intercept = _slope_intercept(days, xs)
        trend = slope * DAYS_PER_MONTH
        if abs(trend) >= 0.05 and slope != 0:
            limit = ACTION_PCT if slope > 0 else -ACTION_PCT
            day = (limit - intercept) / slope
            forecast = date.fromordinal(int(day)) if day > 0 else None

    return SpcSummary(n, xs[-1], cl, mr_bar, sigma, ucl_mr, status_for(xs[-1]), trend, forecast, out)


def _analyse_periods(pts: list[Point], periods: Sequence[tuple[date, date]]) -> SpcSummary:
    """Segmented analysis: every baseline period fixes the limits of its own segment and restarts the CUSUM."""
    periods = sorted(set(periods))
    first = periods[0][0]
    out: list[SpcPoint] = []
    pre = [p for p in pts if p.on < first]
    for i, p in enumerate(pre):
        out.append(SpcPoint(p.on, p.deviation_pct, abs(p.deviation_pct - pre[i - 1].deviation_pct) if i else None,
                            None, 0.0, 0.0, None, pre=True, segment=-1))
    segments: list[dict] = []
    current: Optional[SpcSummary] = None
    for k, (start, ref_to) in enumerate(periods):
        end = periods[k + 1][0] if k + 1 < len(periods) else None
        seg = [p for p in pts if p.on >= start and (end is None or p.on < end)]
        limit = min(ref_to, end - timedelta(days=1)) if end else ref_to      # the reference never reaches into the next segment
        ref_pts = [p for p in seg if start <= p.on <= limit]
        ref = analyse(ref_pts) if len(ref_pts) >= 2 else None
        fixed = (ref.cl, ref.sigma) if ref and ref.cl is not None and ref.sigma else None
        a = analyse(seg, baseline=fixed) if seg else None
        info = dict(start=start, end=end, ref_to=limit, n=len(seg), n_ref=len(ref_pts), own=fixed is None,
                    cl=a.cl if a else None, sigma=a.sigma if a else None)
        segments.append(info)
        if a:
            for sp in a.points:
                sp.segment = k
                out.append(sp)
            current = a
    if current is None:                               # every point is older than the first period: the whole series, as without periods
        return analyse(pts)
    return SpcSummary(len(pts), pts[-1].deviation_pct, current.cl, current.mr_bar, current.sigma, current.ucl_mr,
                      status_for(pts[-1].deviation_pct), current.trend_pct_per_month, current.forecast_out_of_tolerance, out, segments)
