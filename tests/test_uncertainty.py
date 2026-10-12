"""Golden values are cached results of the user's worksheets (sheet "Uncertainty", «Неопределённость»)."""
from datetime import date, timedelta

import pytest

from core import uncertainty as un


def test_photon_stages_match_worksheet():
    b = un.photon_budget()
    assert b.u1 == pytest.approx(1.346291201783626, rel=1e-12)
    assert b.u2 == pytest.approx(0.818535277187245, rel=1e-12)
    assert b.u_type_b == pytest.approx(1.575595125658873, rel=1e-12)


def test_electron_example_matches_worksheet():
    # the worksheet evaluated its plane-parallel branch with R50 < 2: reproduce that case explicitly
    b = un.electron_budget(plane_parallel=True, q0_co60=True, r50=1.5, sigma_a=0.5108836012760901)
    assert b.u1 == pytest.approx(1.0816653826391966, rel=1e-12)
    assert b.u2 == pytest.approx(1.0535653752852738, rel=1e-12)
    assert b.uc == pytest.approx(1.5940520863675773, rel=1e-12)
    assert b.expanded == pytest.approx(3.1881041727351547, rel=1e-12)
    assert b.u_type_b == pytest.approx(1.5099668870541498, rel=1e-12)


def test_electron_kq_component_depends_on_beam_and_chamber():
    def kq(**kw):
        return un.electron_budget(**kw).stage2[4].u_pct
    assert kq(plane_parallel=True, q0_co60=True, r50=1.5) == 0.8
    assert kq(plane_parallel=True, q0_co60=True, r50=3.8) == 0.7        # the worksheet's empty R_50 gave 0.8 here
    assert kq(plane_parallel=False, q0_co60=True, r50=1.5) == 0.7
    assert kq(plane_parallel=True, q0_co60=False, r50=1.5) == 0.4
    assert kq(plane_parallel=True, q0_co60=False, r50=3.8) == 0.2
    assert kq(plane_parallel=False, q0_co60=False, r50=3.8) == 0.2


def test_type_a_is_added_in_quadrature_and_shares_sum_to_100():
    b = un.photon_budget(sigma_a=0.21)
    assert b.uc == pytest.approx((b.u1 ** 2 + b.u2 ** 2 + 0.21 ** 2) ** 0.5)
    shares = b.contributions()
    assert sum(s[3] for s in shares) == pytest.approx(100.0)
    assert shares[0][0].startswith("Калибровка вторичного эталона")        # 1.25 % dominates


def _series(slope_per_month, n=12, start=0.0):
    d0 = date(2026, 1, 1)
    return [(d0 + timedelta(days=30 * i), start + slope_per_month * i) for i in range(n)]


def test_advice_verdicts():
    ok = un.recalibration_advice(_series(0.0), sigma_a=0.2, today=date(2026, 12, 1))
    assert ok.verdict == "норма"
    assert un.recalibration_advice(_series(0.0, start=1.4), sigma_a=0.2).verdict == "наблюдение"
    assert un.recalibration_advice(_series(0.0, start=1.0), sigma_a=0.4).verdict.startswith("ПРЕДУПРЕЖДЕНИЕ")
    assert un.recalibration_advice(_series(0.0, start=2.5), sigma_a=0.2).verdict.startswith("ДЕЙСТВИЕ")
    assert un.recalibration_advice(_series(0.0), sigma_a=0.2, signals=True).verdict == "наблюдение"
    assert un.recalibration_advice([], sigma_a=0.2).verdict == "нет данных"


def test_advice_trend_and_dates():
    a = un.recalibration_advice(_series(0.15), sigma_a=0.2, today=date(2026, 12, 1))
    assert a.trend_pct_per_month == pytest.approx(0.15 * un.DAYS_PER_MONTH / 30, rel=1e-6)
    assert isinstance(a.months_to_tolerance, float) and a.months_to_tolerance > 0
    assert a.trend_date is not None and a.recommended_date == a.trend_date
    flat = un.recalibration_advice(_series(0.0), sigma_a=0.2, last_calibration=date(2026, 1, 1))
    assert flat.months_to_tolerance == "тренда нет" and flat.planned_date == date(2027, 1, 1)
    assert flat.recommended_date == date(2027, 1, 1)


def test_last_calibration_restricts_the_window():
    pts = _series(0.3, n=10)
    cut = pts[6][0]
    a = un.recalibration_advice(pts, sigma_a=0.1, last_calibration=cut)
    assert a.last_deviation == pts[-1][1]
    assert un.recalibration_advice(pts, sigma_a=0.1, last_calibration=pts[-1][0] + timedelta(days=1)).verdict == "нет данных"
