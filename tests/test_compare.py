import datetime as dt
import math
import random

import pytest

from core import compare, spc


def points(values, start=dt.date(2025, 1, 15), per_month=1):
    out = []
    for i, v in enumerate(values):
        m = start.month - 1 + i
        out.append(spc.Point(dt.date(start.year + m // 12, m % 12 + 1, 15), v))
    return out


def noise(seed, n, sigma=0.15):
    rng = random.Random(seed)
    return [rng.gauss(0, sigma) for _ in range(n)]


def test_align_averages_points_of_the_same_month_and_leaves_gaps():
    a = [spc.Point(dt.date(2026, 1, 5), 0.2), spc.Point(dt.date(2026, 1, 25), 0.4), spc.Point(dt.date(2026, 3, 10), 1.0)]
    b = [spc.Point(dt.date(2026, 2, 10), -0.5)]
    months, matrix = compare.align({"6 MV": a, "9 MeV": b})
    assert months == ["2026-01", "2026-02", "2026-03"]
    assert matrix["6 MV"] == [pytest.approx(0.3), None, 1.0] and matrix["9 MeV"] == [None, -0.5, None]


def test_align_can_restrict_the_period():
    pts = points([0.1] * 6)
    months, _ = compare.align({"x": pts}, since=dt.date(2025, 4, 1))
    assert months == ["2025-04", "2025-05", "2025-06"]


def test_a_shift_of_most_energies_in_one_month_is_flagged_as_common():
    n = 12
    series = {f"E{k}": points([v + (1.0 if i == 6 else 0.0) for i, v in enumerate(noise(k, n))]) for k in range(5)}
    months, matrix = compare.align(series)
    flagged = [c for c in compare.common_mode(months, matrix) if c.flagged]
    assert [c.month for c in flagged] == ["2025-07"] and flagged[0].direction == "вверх" and flagged[0].up == 5


def test_one_energy_moving_alone_is_not_a_common_shift():
    series = {f"E{k}": points([v + (2.0 if (k == 0 and i == 6) else 0.0) for i, v in enumerate(noise(k + 10, 12, 0.05))]) for k in range(5)}
    months, matrix = compare.align(series)
    assert not any(c.flagged for c in compare.common_mode(months, matrix))


def test_a_common_shift_needs_enough_beams():
    series = {"a": points([1.0] * 4), "b": points([1.0] * 4)}
    months, matrix = compare.align(series)
    assert not any(c.flagged for c in compare.common_mode(months, matrix))           # two beams are not enough


def test_correlation_tells_shared_drift_from_independent_noise():
    n = 24
    common = noise(1, n, 0.5)
    shared = {f"S{k}": points([c + e for c, e in zip(common, noise(100 + k, n, 0.1))]) for k in range(3)}
    independent = {f"I{k}": points(noise(200 + k, n, 0.5)) for k in range(3)}
    months, matrix = compare.align({**shared, **independent})
    labels, values = compare.correlations(months, matrix)
    idx = {l: i for i, l in enumerate(labels)}
    assert values[idx["S0"]][idx["S1"]] > 0.8 and values[idx["S1"]][idx["S2"]] > 0.8
    assert abs(values[idx["I0"]][idx["I1"]]) < 0.6
    assert all(values[i][i] == 1.0 for i in range(len(labels)))


def test_short_overlap_gives_no_correlation():
    months, matrix = compare.align({"a": points([0.1, 0.2, 0.3]), "b": points([0.2, 0.1, 0.4])})
    labels, values = compare.correlations(months, matrix, min_overlap=6)
    assert values[0][1] is None
    assert compare.pearson([1, 1, 1], [1, 2, 3]) is None and compare.pearson([1, 2], [1, 2]) is None
    assert compare.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


def test_beam_summary_reports_status_trend_and_signals():
    calm = compare.beam_summary("6 MV", points(noise(5, 24, 0.15)))
    assert calm["n"] == 24 and calm["status"] == "норма" and calm["out_of_tolerance"] == 0
    jumpy = compare.beam_summary("10 MV", points([0.1] * 10 + [2.8] + [0.0] * 5))
    assert jumpy["n_3sigma"] >= 1 and jumpy["out_of_tolerance"] == 1 and jumpy["last_signal"] is not None
    drift = compare.beam_summary("15 MV", points([0.05 * i for i in range(24)]))
    assert drift["trend"] == pytest.approx(0.05 * 30.4375 / 30, rel=0.02) and drift["forecast"] is not None
    empty = compare.beam_summary("none", [])
    assert empty["n"] == 0 and empty["last"] is None and empty["mean"] is None


def test_interpretation_hints():
    months, matrix = compare.align({f"E{k}": points([1.0 if i == 4 else 0.0 for i in range(8)]) for k in range(4)})
    common = compare.common_mode(months, matrix)
    labels, values = compare.correlations(months, matrix)
    text = " ".join(compare.interpretation(common, labels, values))
    assert "Общий сдвиг" in text and "общую причину" in text
    calm_months, calm = compare.align({f"E{k}": points(noise(300 + k, 12, 0.05)) for k in range(4)})
    calm_text = " ".join(compare.interpretation(compare.common_mode(calm_months, calm), *compare.correlations(calm_months, calm)))
    assert "не найдено" in calm_text
