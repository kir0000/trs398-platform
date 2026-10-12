"""Comparing the output trends of several beams (energies) of one linac.

Questions it answers:
* which beams are in control, drifting or out of tolerance (one row per beam, from the SPC rules);
* did several energies move together in the same month (a common cause such as the monitor chamber, the
  environment or the dosimetry), or did one energy move alone (an energy-specific cause)?
* how closely do the energies follow each other over time (Pearson correlation of their monthly deviations)?

Deviations are percent from the nominal 1 cGy/MU; points of one beam in the same calendar month are averaged.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import ceil, sqrt
from typing import Mapping, Optional, Sequence

from core import spc

SHIFT_PCT = 0.3            # a beam "moves" in a month when it deviates by at least this much
MIN_BEAMS = 3              # a common shift needs at least this many beams with data in the month
SHARE = 0.7                # ... and this share of them moving in the same direction
MIN_OVERLAP = 6            # months two beams must have in common for a correlation


def month_key(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def align(series: Mapping[str, Sequence[spc.Point]], since=None):
    """Months (sorted) and, per beam label, the monthly mean deviation (None where the beam has no data)."""
    per_beam: dict[str, dict[str, list[float]]] = {}
    months: set[str] = set()
    for label, points in series.items():
        bucket: dict[str, list[float]] = defaultdict(list)
        for p in points:
            if since is None or p.on >= since:
                bucket[month_key(p.on)].append(p.deviation_pct)
        per_beam[label] = bucket
        months.update(bucket)
    ordered = sorted(months)
    matrix = {label: [sum(b[m]) / len(b[m]) if m in b else None for m in ordered] for label, b in per_beam.items()}
    return ordered, matrix


@dataclass
class MonthSummary:
    month: str
    n: int
    mean: float
    spread: float                  # max - min across the beams
    up: int
    down: int
    flagged: bool
    direction: Optional[str]       # direction text when flagged: "вверх" (up) / "вниз" (down); the interface catalog translates it


def common_mode(months: Sequence[str], matrix: Mapping[str, Sequence[Optional[float]]], shift: float = SHIFT_PCT,
                min_beams: int = MIN_BEAMS, share: float = SHARE) -> list[MonthSummary]:
    """Per month: how many beams moved up or down and whether that looks like one common cause."""
    out = []
    for i, m in enumerate(months):
        vals = [row[i] for row in matrix.values() if row[i] is not None]
        if not vals:
            continue
        up, down = sum(v >= shift for v in vals), sum(v <= -shift for v in vals)
        mean = sum(vals) / len(vals)
        need = max(min_beams, ceil(share * len(vals)))
        flagged = len(vals) >= min_beams and max(up, down) >= need and abs(mean) >= shift
        out.append(MonthSummary(m, len(vals), mean, max(vals) - min(vals), up, down, flagged,
                                ("вверх" if mean > 0 else "вниз") if flagged else None))
    return out


def pearson(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx, syy = sum((a - mx) ** 2 for a in x), sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / sqrt(sxx * syy)


def correlations(months: Sequence[str], matrix: Mapping[str, Sequence[Optional[float]]], min_overlap: int = MIN_OVERLAP):
    """Matrix of Pearson correlations of the beams' monthly deviations (None where the overlap is too short)."""
    labels = list(matrix)
    values = []
    for a in labels:
        row = []
        for b in labels:
            pairs = [(x, y) for x, y in zip(matrix[a], matrix[b]) if x is not None and y is not None]
            row.append(1.0 if a == b else (pearson([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= min_overlap else None))
        values.append(row)
    return labels, values


def beam_summary(label: str, points: Sequence[spc.Point], periods=None) -> dict:
    """One row of the comparison table: the SPC analysis of a single beam."""
    s = spc.analyse(points, periods=periods)
    signals = [p for p in s.points if p.signal or p.cusum_signal]
    return {
        "label": label, "n": s.n, "last": s.last, "last_date": s.points[-1].on if s.points else None,
        "mean": (sum(p.deviation_pct for p in s.points) / s.n) if s.n else None,
        "sigma": s.sigma, "trend": s.trend_pct_per_month, "forecast": s.forecast_out_of_tolerance, "status": s.status,
        "n_3sigma": sum(1 for p in s.points if p.signal == "за 3σ"),
        "n_rules": sum(1 for p in s.points if p.signal and p.signal != "за 3σ"),
        "n_cusum": sum(1 for p in s.points if p.cusum_signal),
        "last_signal": signals[-1].on if signals else None,
        "out_of_tolerance": sum(1 for p in s.points if abs(p.deviation_pct) > spc.ACTION_PCT),
    }


def interpretation(common: Sequence[MonthSummary], corr_labels: Sequence[str], corr_values) -> list[str]:
    """Plain-language hints for the physicist (they are hints, the decision is theirs)."""
    hints = []
    flagged = [c for c in common if c.flagged]
    if flagged:
        months = ", ".join(c.month for c in flagged[-6:])
        hints.append(f"Общий сдвиг нескольких энергий в одном месяце ({months}): ищите общую причину — "
                     "монитор/камера-монитор, температуру и давление, электрометр, калибровку дозиметра.")
    else:
        hints.append("Общих сдвигов нескольких энергий в один месяц не найдено: отклонения носят индивидуальный характер.")
    pairs = [(corr_values[i][j], corr_labels[i], corr_labels[j]) for i in range(len(corr_labels))
             for j in range(i + 1, len(corr_labels)) if corr_values[i][j] is not None]
    if pairs:
        mean_r = sum(p[0] for p in pairs) / len(pairs)
        if mean_r >= 0.6:
            hints.append(f"Энергии движутся согласованно (средняя корреляция {mean_r:.2f}): вероятна общая причина дрейфа.")
        elif mean_r <= 0.2:
            hints.append(f"Энергии почти не связаны (средняя корреляция {mean_r:.2f}): отклонения случайны или связаны с настройкой "
                         "конкретной энергии.")
        else:
            hints.append(f"Умеренная связь между энергиями (средняя корреляция {mean_r:.2f}).")
    return hints
