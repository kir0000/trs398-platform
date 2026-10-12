"""Decimal separator: a comma on Russian pages, a point on English ones, everywhere a person reads a number."""
import datetime as dt
import json
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app import i18n
from tests.test_app import client, post, q, world  # noqa: F401  (fixtures are discovered here)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from decimal_scan import visible_points  # noqa: E402


# --------------------------------------------------------------------------- the conversion itself
def test_ru_text_numbers_get_a_comma_but_dates_dois_addresses_and_versions_do_not():
    page = ('<html lang="ru"><body><p>Откл. 0.18 %, -0.05, +1.25 и 100.63 кПа; дата 15.09.2026; v2.0; Rev.1; 192.168.1.20; '
            'doi 10.1002/acm2.14339; u = 2.5.</p><p>TPR<sub>20,10</sub> = 0.6119 и 1.5 г/см²</p></body></html>')
    out = i18n.translate_html(page, "ru")
    assert "Откл. 0,18 %, -0,05, +1,25 и 100,63 кПа" in out and "u = 2,5." in out and "0,6119" in out and "1,5 г/см²" in out
    assert "15.09.2026" in out and "v2.0" in out and "192.168.1.20" in out and "10.1002/acm2.14339" in out and "<sub>20,10</sub>" in out


def test_ru_conversion_leaves_scripts_code_attributes_and_hidden_values_alone():
    page = ('<html lang="ru"><head><style>.a{width:1.5em}</style><script>var x = 1.5; var s = "0.25 и 2.5";</script></head><body>'
            '<code>python 3.12</code><pre>APP_PORT=8.0</pre>'
            '<input name="a" value="1.25" placeholder="24.36"><input type="hidden" name="d" value="0.6000">'
            '<option value="0.05138" data-nd="0.05138">0.05138</option><a href="/x?v=1.5">1.5</a></body></html>')
    out = i18n.translate_html(page, "ru")
    assert "width:1.5em" in out and 'var x = 1.5; var s = "0.25 и 2.5";' in out
    assert "<code>python 3.12</code>" in out and "APP_PORT=8.0" in out
    assert 'value="1,25"' in out and 'placeholder="24,36"' in out                       # what a person reads and types
    assert 'value="0.6000"' in out and 'value="0.05138"' in out and 'data-nd="0.05138"' in out and 'href="/x?v=1.5"' in out
    assert ">0,05138</option>" in out and ">1,5</a>" in out


def test_english_keeps_the_point_and_the_two_conversions_do_not_fight():
    ru = i18n.translate_html('<html lang="ru"><body><p>Откл. 0,18 % и 2.5 мм</p><input value="1,5"></body></html>', "en")
    assert "0.18" in ru and 'value="1.5"' in ru
    again = i18n.translate_html(i18n.translate_html('<html lang="ru"><body>0.18</body></html>', "ru"), "ru")
    assert "0,18" in again                                                               # idempotent


# --------------------------------------------------------------------------- every page
@pytest.fixture(scope="module")
def ru_pages(client, world):
    sys.path.insert(0, str(ROOT / "tools"))
    import seed_demo
    with psycopg.connect(client.owner_url, row_factory=dict_row) as conn:
        seed_demo.seed(conn, 12, dt.date(2026, 9, 1))
        conn.commit()
    adm = world["adm"]
    one = lambda sql: q(client, sql)[0][0]
    beam = one("SELECT b.id FROM beams b JOIN linacs l ON l.id = b.linac_id WHERE l.name = 'TrueBeam' AND b.modality = 'photon' ORDER BY b.id LIMIT 1")
    ebeam = one("SELECT b.id FROM beams b JOIN linacs l ON l.id = b.linac_id WHERE l.name = 'TrueBeam' AND b.modality = 'electron' ORDER BY b.id LIMIT 1")
    linac = one("SELECT id FROM linacs WHERE name = 'TrueBeam'")
    sid = one(f"SELECT id FROM measurement_sessions WHERE beam_id = {beam} ORDER BY id LIMIT 1")
    esid = one(f"SELECT id FROM measurement_sessions WHERE beam_id = {ebeam} ORDER BY id LIMIT 1")
    cal = one("SELECT id FROM calibrations ORDER BY id LIMIT 1")
    urls = ["/measurements", "/measurements?status=approved", "/measurements/new?modality=photon", "/measurements/new?modality=electron",
            f"/measurements/{sid}", f"/measurements/{sid}/print", f"/measurements/{sid}/print?unc=full", f"/measurements/{esid}",
            f"/measurements/{esid}/print?unc=full", "/equipment", "/equipment?tab=dosimeters", "/equipment?tab=reference", f"/equipment/calibration/{cal}/edit", "/trends", f"/trends?beam_id={beam}",
            f"/trends?beam_id={ebeam}", "/uncertainty", f"/uncertainty?beam_id={beam}", f"/uncertainty?beam_id={ebeam}", "/compare",
            f"/compare?linac_id={linac}", "/help", "/admin/users", "/admin/audit", "/admin/backups", "/admin/purge"]
    return {u: adm.get(u + ("&" if "?" in u else "?") + "lang=ru") for u in urls}


def test_no_decimal_point_is_left_on_russian_pages(ru_pages):
    bad = {}
    for url, r in ru_pages.items():
        if "text/html" not in r.headers.get("content-type", ""):
            continue
        left = visible_points(r.text)
        if left:
            bad[url] = sorted(set(left))[:8]
    assert not bad, json.dumps(bad, ensure_ascii=False, indent=1)[:3000]


def test_the_values_a_person_types_back_are_accepted_with_a_comma(world, client):
    phys = world["phys"]
    page = f"/uncertainty?beam_id={world['beam_id']}"
    html = phys.get(page + "&lang=ru").text
    assert 'name="tolerance" value="2,0"' in html and 'name="observe" value="1,0"' in html            # the form is shown with commas
    assert phys.get(page + "&tolerance=2,5&observe=1,2&lang=ru").status_code == 200                    # and read back with commas
    assert phys.get(page + "&tolerance=2.5&observe=1.2&lang=ru").status_code == 200                    # a point is still fine
    en = phys.get(page + "&lang=en").text
    assert 'name="tolerance" value="2.0"' in en


def test_russian_chart_pages_load_the_russian_chart_locale_and_english_ones_do_not(ru_pages, world):
    for url in ("/trends?beam_id=1", "/uncertainty?beam_id=1", "/compare"):
        match = [u for u in ru_pages if u.startswith(url.split("?")[0]) and "beam_id" in u or u == url]
        assert match, url
    assert all("/static/plotly-ru.js" in ru_pages[u].text for u in ru_pages if u.startswith(("/trends?beam", "/uncertainty?beam", "/compare")))
    en = world["adm"].get("/trends?lang=en").text
    assert "plotly-ru.js" not in en
    r = world["adm"].get("/static/plotly-ru.js")
    assert r.status_code == 200 and "decimal: ','" in r.text


def test_english_pages_have_no_decimal_comma(client, world, ru_pages):
    import re
    from decimal_scan import visible_points      # noqa: F401  (same module; scanning below is the reverse case)
    comma = re.compile(r"(?<![A-Za-z0-9_.,/])(\d+),(\d+)(?!\d)")
    bad = {}
    for url in ru_pages:
        r = world["adm"].get(url + ("&" if "?" in url else "?") + "lang=en")
        if "text/html" not in r.headers.get("content-type", ""):
            continue
        html = re.sub(r"<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>|<pre\b.*?</pre>|<code\b.*?</code>|<sub>.*?</sub>", " ", r.text, flags=re.S)
        text = [n for n in re.sub(r"<[^>]+>", "\x00", html).split("\x00") if n.strip()]
        left = [m.group(0) for n in text for m in comma.finditer(n)]
        if left:
            bad[url] = sorted(set(left))[:8]
    assert not bad, json.dumps(bad, ensure_ascii=False, indent=1)[:2500]


def test_chart_numbers_are_formatted_by_the_chart_locale_not_by_the_code(ru_pages):
    """The labels of the charts use d3 formats (a comma on Russian pages, a point on English ones): no toFixed() text and no preformatted strings."""
    for url in ("/uncertainty?beam_id=1", "/compare"):
        pages = [r.text for u, r in ru_pages.items() if u.split("?")[0] == url.split("?")[0] and "text/html" in r.headers.get("content-type", "")]
        assert pages, url
        for html in pages:
            assert "toFixed(1) + ' %'" not in html and "corr_text" not in html
    page = next(r.text for u, r in ru_pages.items() if u.startswith("/uncertainty?beam_id"))
    assert "texttemplate: '%{x:.1f} %'" in page and "%{customdata:.2f}" in page
