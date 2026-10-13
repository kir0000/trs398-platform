"""The reminder about the calibration of the chambers: 3 calendar months before the expiry, and after it."""
import datetime as dt

from app.main import add_months, calibration_state
from tests.test_app import client, world  # noqa: F401  (fixtures are discovered here)
from tests.test_equipment_params import add_calibration


def test_add_months_keeps_the_end_of_the_month():
    assert add_months(dt.date(2026, 11, 30), 3) == dt.date(2027, 2, 28)
    assert add_months(dt.date(2026, 10, 31), 3) == dt.date(2027, 1, 31)
    assert add_months(dt.date(2026, 12, 15), 3) == dt.date(2027, 3, 15)
    assert add_months(dt.date(2028, 11, 30), 3) == dt.date(2029, 2, 28)


def test_state_changes_exactly_three_months_before():
    today = dt.date(2026, 10, 13)
    st = lambda d: calibration_state({"valid_until": d}, today)["state"]            # noqa: E731
    assert st(dt.date(2027, 1, 13)) == "soon"            # exactly 3 months
    assert st(dt.date(2027, 1, 14)) == "ok"
    assert st(dt.date(2026, 10, 13)) == "soon"           # the last day is still valid
    assert st(dt.date(2026, 10, 12)) == "expired"
    assert calibration_state({"valid_until": None}, today)["state"] == "none"


def test_the_banner_lists_expiring_chambers_by_their_newest_calibration(world, client):
    today = dt.date.today()
    add_calibration(world, client, serial_no="REM-SOON", valid_until=(today + dt.timedelta(days=40)).isoformat())
    add_calibration(world, client, serial_no="REM-FAR", valid_until=(today + dt.timedelta(days=400)).isoformat())
    add_calibration(world, client, serial_no="REM-GONE", valid_until=(today - dt.timedelta(days=5)).isoformat())
    # a chamber with an old expired calibration and a new valid one is not reminded about
    add_calibration(world, client, serial_no="REM-RENEWED", calibrated_on="2020-01-01", valid_until="2021-01-01")
    add_calibration(world, client, serial_no="REM-RENEWED", calibrated_on=today.isoformat(), valid_until=(today + dt.timedelta(days=700)).isoformat())
    html = world["phys"].get("/measurements").text
    assert "Калибровка камер:" in html
    assert "REM-SOON" in html and "осталось дней: 40" in html
    assert "REM-GONE" in html and "срок истёк" in html and "запрещены" in html
    assert "REM-FAR" not in html and "REM-RENEWED" not in html
    assert html.index("REM-GONE") < html.index("REM-SOON")          # the expired one first
    world["phys"].get("/lang/en")
    en = world["phys"].get("/measurements").text
    assert "Chamber calibration:" in en and "days left: 40" in en and "Калибровка" not in en
