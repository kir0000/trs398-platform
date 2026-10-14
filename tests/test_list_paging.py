"""The list of measurements: pages instead of a silent cut-off, filters, nothing is lost between the pages."""
import re

import pytest

from app.routes import measurements as routes
from tests.test_app import client, create_measurement, post, q, world  # noqa: F401  (fixtures are discovered here)

DATES = ["2025-01-10", "2025-02-10", "2025-03-10", "2025-04-10", "2025-05-10", "2025-06-10", "2025-07-10", "2025-08-10"]


def ids_of(html):
    return re.findall(r'<td><a href="/measurements/(\d+)">', html)


@pytest.fixture(scope="module")
def many(world, client):
    from tests.test_equipment_params import add_calibration
    cid = add_calibration(world, client, serial_no="LIST-1")
    made = []
    for d in DATES:
        r = create_measurement(world, "phys", calibration_id=cid, measured_on=d)
        assert r.status_code == 303, r.text[:200]
        made.append(int(r.headers["location"].rsplit("/", 1)[1]))
    return made


def test_pages_hold_everything_and_lose_nothing(world, client, many, monkeypatch):
    monkeypatch.setattr(routes, "LIST_PAGE_SIZE", 3)
    total = q(client, "SELECT count(*) FROM measurement_sessions")[0][0]
    pages = -(-total // 3)
    seen = []
    for p in range(1, pages + 1):
        html = world["view"].get(f"/measurements?page={p}").text
        got = ids_of(html)
        assert 1 <= len(got) <= 3 and f"страница {p} из {pages}" in html
        seen += got
    assert len(seen) == total and len(set(seen)) == total                               # every record exactly once
    assert sorted(map(int, seen)) == sorted(r[0] for r in q(client, "SELECT id FROM measurement_sessions"))
    first = world["view"].get("/measurements?page=1").text
    assert f"Записей: {total}" in first and f"показаны 1–3 (страница 1 из {pages})" in first and "Вперёд" in first and "Назад" not in first
    last = world["view"].get(f"/measurements?page={pages}").text
    assert "Вперёд" not in last and "Назад" in last
    assert world["view"].get("/measurements?page=999").text.count("страница") >= 1 and ids_of(world["view"].get("/measurements?page=999").text) == ids_of(last)
    assert ids_of(world["view"].get("/measurements?page=0").text) == ids_of(first)                    # a page below the first is the first


def test_the_newest_records_come_first(world, client, many):
    got = [int(x) for x in ids_of(world["view"].get("/measurements").text)]
    dates = [q(client, "SELECT measured_on FROM measurement_sessions WHERE id=%s", i)[0][0] for i in got]
    assert dates == sorted(dates, reverse=True)


def test_filters_narrow_the_list_and_stay_in_the_links(world, client, many, monkeypatch):
    v = world["view"]
    html = v.get("/measurements?from=2025-03-01&to=2025-05-31").text
    got = {int(x) for x in ids_of(html)}
    dates = {q(client, "SELECT measured_on FROM measurement_sessions WHERE id=%s", i)[0][0].isoformat() for i in got}
    assert dates == {"2025-03-10", "2025-04-10", "2025-05-10"}
    sid = many[0]
    no = q(client, "SELECT protocol_no FROM measurement_sessions WHERE id=%s", sid)[0][0]
    assert [int(x) for x in ids_of(v.get(f"/measurements?q={no}").text)] == [sid]                 # by the protocol number
    assert len(ids_of(v.get("/measurements?q=Phys").text)) >= len(many)                            # by the author
    assert ids_of(v.get("/measurements?q=нет-такого").text) == [] and "Записей по этим условиям нет" in v.get("/measurements?q=нет-такого").text
    beam = q(client, "SELECT beam_id FROM measurement_sessions WHERE id=%s", sid)[0][0]
    assert len(ids_of(v.get(f"/measurements?beam={beam}").text)) >= len(many)
    assert ids_of(v.get("/measurements?beam=999999").text) == []
    assert len(ids_of(v.get("/measurements?status=approved").text)) == q(client, "SELECT count(*) FROM measurement_sessions WHERE status='approved'")[0][0]
    assert len(ids_of(v.get("/measurements?from=garbage&linac=x&beam=").text)) == len(ids_of(v.get("/measurements").text))   # bad values are ignored
    monkeypatch.setattr(routes, "LIST_PAGE_SIZE", 2)
    page = v.get("/measurements?from=2025-01-01&q=Phys&status=draft").text
    assert re.search(r'href="/measurements\?page=2&[^"]*from=2025-01-01[^"]*q=Phys[^"]*status=draft', page) or "from=2025-01-01" in page


def test_the_form_shows_the_chosen_values_and_the_status_buttons_keep_working(world, client, many):
    html = world["view"].get("/measurements?from=2025-03-01&q=abc").text
    assert 'name="from" value="2025-03-01"' in html and 'name="q" value="abc"' in html and 'name="linac"' in html and 'name="beam"' in html
    assert "/measurements?status=draft" in html and "Сбросить" in html


def test_english_page_has_no_russian_left(world, client, many, monkeypatch):
    from app import i18n
    monkeypatch.setattr(routes, "LIST_PAGE_SIZE", 3)
    s = world["view"]
    s.get("/lang/en")
    try:
        html = s.get("/measurements?page=2&from=2025-01-01").text
        left = [t for t in i18n.leftovers(html) if t != "Language / Язык"]
        assert not left, left[:5]
        assert "page 2 of" in html and "Records:" in html
    finally:
        s.get("/lang/ru")
