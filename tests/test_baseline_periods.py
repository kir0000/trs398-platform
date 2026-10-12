"""Baseline periods restart the statistics: limits and CUSUM of each segment, grey points before the first period."""
from datetime import date, timedelta

import pytest

from core import spc
from tests.test_app import client, post, q, world  # noqa: F401  (fixtures are discovered here)

VALUES = [0.1, 0.2, 0.1, 0.0, 0.3, 0.1, -0.5, -0.4, -0.5, -0.4, -0.5, -0.45, -0.5, -0.4]
POINTS = [spc.Point(date(2024, 1, 1) + timedelta(days=30 * i), v) for i, v in enumerate(VALUES)]


def test_points_before_the_first_period_have_no_limits_and_no_signals():
    s = spc.analyse(POINTS, periods=[(date(2024, 7, 1), date(2025, 3, 1))])
    pre = [p for p in s.points if p.pre]
    assert len(pre) == 7 and all(p.signal is None and p.cusum_signal is None and p.segment == -1 for p in pre)
    assert s.cl == pytest.approx(-0.45) and len(s.segments) == 1 and s.segments[0]["n"] == 7
    assert s.n == 14 and [p.segment for p in s.points if not p.pre] == [0] * 7


def test_each_period_has_its_own_limits_and_restarts_the_cusum():
    s = spc.analyse(POINTS, periods=[(date(2024, 1, 1), date(2024, 6, 1)), (date(2024, 7, 1), date(2025, 3, 1))])
    first, second = s.segments
    assert first["cl"] == pytest.approx(0.1333, abs=1e-3) and second["cl"] == pytest.approx(-0.45)
    assert [p.segment for p in s.points] == [0] * 7 + [1] * 7
    after = [p for p in s.points if p.segment == 1]
    assert abs(after[0].cusum_plus) < 0.05 and after[0].cusum_minus == 0.0 and all(p.cusum_signal is None for p in after)   # the sums restart: the shift is the new normal
    assert s.points[6].signal == "за 3σ"                                                   # but the jump itself is seen against the old limits
    whole = spc.analyse(POINTS)
    assert whole.points[-1].cusum_signal is not None or whole.points[-1].cusum_minus < -1        # without periods the shift keeps signalling


def test_a_period_with_less_than_two_points_uses_the_limits_of_its_segment():
    s = spc.analyse(POINTS, periods=[(date(2024, 1, 1), date(2024, 1, 5))])
    assert s.segments[0]["own"] and s.segments[0]["cl"] == pytest.approx(sum(VALUES) / len(VALUES))


def test_periods_are_added_listed_and_removed(world, client):
    adm, bid = world["adm"], world["beam_id"]
    page = f"/trends?beam_id={bid}"
    for f, t in (("2023-10-01", "2024-06-30"), ("2025-01-01", "2025-06-30")):
        assert post(adm, "/trends/baseline", dict(beam_id=bid, from_date=f, to_date=t), page="/measurements").status_code == 303
    assert q(client, "SELECT count(*) FROM spc_baseline WHERE beam_id=%s", bid)[0][0] == 2
    assert post(adm, "/trends/baseline", dict(beam_id=bid, from_date="2025-01-01", to_date="2025-08-01"), page="/measurements").status_code == 303
    assert q(client, "SELECT count(*) FROM spc_baseline WHERE beam_id=%s", bid)[0][0] == 2          # the same start only moves the end
    import psycopg
    with psycopg.connect(client.owner_url) as conn:                  # a journal for the page to draw
        for i in range(8):
            conn.execute("INSERT INTO legacy_journal(beam_id, measured_on, deviation_pct, dw_zmax, source_file) VALUES (%s, %s, %s, %s, 'test')",
                         (bid, date(2024, 1, 1) + timedelta(days=60 * i), 0.1 * (i % 3), 0.01))
        conn.commit()
    html = world["view"].get(page).text
    assert "Начало отрезка" in html and "01.01.2025" in html and "до базового периода" in html
    row = q(client, "SELECT id FROM spc_baseline WHERE beam_id=%s ORDER BY from_date LIMIT 1", bid)[0][0]
    assert post(world["rev"], "/trends/baseline/delete", dict(id=row), page="/measurements").status_code == 403
    assert post(adm, "/trends/baseline/delete", dict(id=row), page="/measurements").status_code == 303
    assert post(adm, "/trends/baseline/delete", dict(id=row), page="/measurements").status_code == 404
    assert q(client, "SELECT count(*) FROM spc_baseline WHERE beam_id=%s", bid)[0][0] == 1
    with psycopg.connect(client.owner_url) as conn:
        conn.execute("DELETE FROM spc_baseline")
        conn.commit()
