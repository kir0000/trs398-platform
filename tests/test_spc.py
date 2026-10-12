import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from core import spc

DATA = Path(__file__).parent / "data"


def load(name):
    if not (DATA / f"{name}_journal.json").exists():
        pytest.skip("private journal fixture not present (tests/data is not published)")
    entries = json.loads((DATA / f"{name}_journal.json").read_text(encoding="utf-8"))
    return entries, [spc.Point(date.fromisoformat(e["date"]), e["deviation_pct"]) for e in entries]


def test_summary_matches_worksheet_trend_sheet():
    # cached values of the sheet "Trend" («Тренд») in the photon worksheet
    _, pts = load("photon")
    s = spc.analyse(pts)
    assert s.n == 36
    assert s.last == pytest.approx(-0.178519473152082, rel=1e-12)
    assert s.cl == pytest.approx(0.009654759352790372, rel=1e-12)
    assert s.trend_pct_per_month == pytest.approx(-0.004065125363333066, rel=1e-9)
    assert s.status == "норма"
    assert s.forecast_out_of_tolerance is None


def test_three_sigma_signal_lands_on_the_record_the_physicist_annotated():
    entries, pts = load("photon")
    s = spc.analyse(pts)
    flagged = [i for i, p in enumerate(s.points) if p.signal == "за 3σ"]
    assert len(flagged) == 1
    assert "3σ" in entries[flagged[0]]["note"]


def test_sigma_from_average_moving_range():
    pts = [spc.Point(date(2026, 1, d), v) for d, v in enumerate([0.0, 0.2, -0.1, 0.1], start=1)]
    s = spc.analyse(pts)
    mrs = [0.2, 0.3, 0.2]
    assert s.mr_bar == pytest.approx(sum(mrs) / 3)
    assert s.sigma == pytest.approx(sum(mrs) / 3 / 1.128)
    assert s.ucl_mr == pytest.approx(3.267 * sum(mrs) / 3)


def test_eight_in_a_row_on_one_side():
    vals = [0.1] * 8 + [-0.5, 0.5, -0.5, 0.5]       # first eight above CL=0? use explicit baseline
    pts = [spc.Point(date(2026, 1, 1) + timedelta(days=i), v) for i, v in enumerate(vals)]
    s = spc.analyse(pts, baseline=(0.0, 1.0))
    assert s.points[7].signal == "8 подряд по одну сторону"
    assert s.points[6].signal is None


def test_cusum_detects_sustained_shift():
    pts = [spc.Point(date(2026, 1, 1) + timedelta(days=i), 1.0) for i in range(12)]
    s = spc.analyse(pts, baseline=(0.0, 0.5))      # k = 0.25, H = 2.5; each step adds 0.75
    assert s.points[0].cusum_plus == pytest.approx(0.75)
    assert any(p.cusum_signal == "CUSUM+: сдвиг вверх" for p in s.points)


def test_status_thresholds():
    assert spc.status_for(0.9) == "норма"
    assert spc.status_for(1.5).startswith("наблюдение")
    assert spc.status_for(-2.5).startswith("ДЕЙСТВИЕ")


def test_forecast_for_drifting_output():
    pts = [spc.Point(date(2026, 1, 1) + timedelta(days=7 * i), 0.1 * i) for i in range(10)]    # rises ~0.43 %/month
    s = spc.analyse(pts)
    assert s.trend_pct_per_month == pytest.approx(0.1 / 7 * spc.DAYS_PER_MONTH, rel=1e-9)
    assert s.forecast_out_of_tolerance is not None and s.forecast_out_of_tolerance > date(2026, 3, 1)


def test_empty_and_tiny_series_do_not_crash():
    assert spc.analyse([]).status == "нет данных"
    one = spc.analyse([spc.Point(date(2026, 1, 1), 0.3)])
    assert one.cl is None and one.sigma is None and one.points[0].signal is None
