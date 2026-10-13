"""Two interface languages: the phrase catalog covers the whole interface, pages come out in English without Russian leftovers."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

from tests import sqlcompat
import pytest
from tests.sqlcompat import dict_row
from app import i18n
from tests.test_app import client, q, world  # noqa: F401  (fixtures are discovered here)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import i18n_extract  # noqa: E402

# Russian text that is data of the test database, not interface text
ALLOWED = {"Language / Язык"} | i18n_extract.LOGIC_WORDS     # a bilingual label; words that scripts compare with data


# --------------------------------------------------------------------------- the mechanism
def test_translation_of_text_attributes_and_scripts():
    cat = i18n.catalog()
    assert cat["Сохранить"] == "Save"
    page = ('<html lang="ru"><head><title>x</title><script>var m = "Сохранить"; var n = \'Отмена\'; var j = "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c";'
            "function comma(x){return (x||'').replace('.', ',');}</script></head><body>"
            '<button title="Сохранить" value="Сохранить">Сохранить</button> <i>k</i><sub>20,10</sub> 1,5 кПа'
            '<input value="24,3 24,2" name="m1"> <span data-help="&lt;i&gt;Q&lt;/i&gt; Сохранить">?</span></body></html>')
    out = i18n.translate_html(page, "en")
    assert '<html lang="en">' in out and ">Save</button>" in out and 'title="Save"' in out
    assert 'value="Сохранить"' in out                                              # what the server reads back is never translated
    assert 'var m = "Save"' in out and "var n = 'Cancel'" in out and 'var j = "Save"' in out
    assert "<sub>20,10</sub>" in out and "1.5 kPa" in out and 'value="24.3 24.2"' in out    # index names keep the comma, numbers get the point
    assert ".replace(',', '.')" in out
    assert "&lt;i&gt;Q&lt;/i&gt; Save" in out
    assert i18n.translate_html(page, "ru") == page                                  # Russian pages are untouched


def test_a_phrase_never_matches_inside_a_longer_russian_word():
    assert i18n.translate_plain("Вход") == "Sign in"
    assert i18n.translate_plain("Входящий") == "Входящий"                          # "Вход" is not cut out of another word


def test_language_choice_session_cookie_and_query(world):
    s = world["adm"]
    assert "Выйти" in s.get("/measurements").text
    r = s.get("/lang/en?next=/measurements")
    assert r.status_code == 303 and r.headers["location"] == "/measurements"
    page = s.get("/measurements").text
    assert "Sign out" in page and "Выйти" not in page and '<html lang="en">' in page
    assert "Выйти" in s.get("/measurements?lang=ru").text                          # the request overrides the session
    assert s.get("/lang/xx").status_code == 404
    assert s.get("/lang/ru?next=//evil.example").headers["location"] == "/"       # no open redirect
    s.get("/lang/ru")
    assert "Выйти" in s.get("/measurements").text


def test_confirmation_word_of_the_purge_is_accepted_in_both_languages():
    from app.main import PURGE_CONFIRMATIONS
    assert {"УДАЛИТЬ", "DELETE"} <= set(PURGE_CONFIRMATIONS)


# --------------------------------------------------------------------------- coverage
def test_every_phrase_of_the_interface_has_an_english_text():
    missing = sorted(s for s in i18n_extract.collect() if not i18n.catalog().get(s))
    assert not missing, f"{len(missing)} phrases without English text, first: {missing[:15]}"


@pytest.fixture(scope="module")
def pages(client, world):
    """Every kind of page of a database with demo data, fetched in English."""
    sys.path.insert(0, str(ROOT / "tools"))
    import seed_demo
    with sqlcompat.connect(client.owner_url, row_factory=dict_row) as conn:
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
            f"/measurements/{sid}", f"/measurements/{sid}/print", f"/measurements/{sid}/print?unc=full", f"/measurements/{sid}/print?unc=none",
            f"/measurements/{esid}", f"/measurements/{esid}/print", f"/measurements/{esid}/print?unc=full",
            f"/measurements/reference?beam_id={beam}", "/equipment", "/equipment?tab=dosimeters", "/equipment?tab=reference", f"/equipment/calibration/{cal}/edit",
            "/trends", f"/trends?beam_id={beam}", f"/trends?beam_id={ebeam}", "/uncertainty", f"/uncertainty?beam_id={beam}",
            f"/uncertainty?beam_id={ebeam}", "/compare", f"/compare?linac_id={linac}", f"/compare?linac_id={linac}&modality=electron&months=6",
            "/help", "/admin/users", "/admin/audit", "/admin/backups", "/admin/purge", "/measurements/999999", "/lang/zz"]
    out = {}
    for u in urls:
        r = adm.get(u + ("&" if "?" in u else "?") + "lang=en")
        out[u] = r
    return out


def test_pages_have_no_russian_left_in_english(pages):
    bad = {}
    for url, r in pages.items():
        if "text/html" not in r.headers.get("content-type", ""):
            continue
        left = [t for t in i18n.leftovers(r.text) if t not in ALLOWED]
        if left:
            bad[url] = left[:6]
    assert not bad, json.dumps(bad, ensure_ascii=False, indent=1)[:4000]


def test_error_pages_and_live_preview_are_translated(world, client):
    adm = world["adm"]
    page = adm.get("/measurements/999999?lang=en")
    assert page.status_code == 404 and not [t for t in i18n.leftovers(page.text) if t not in ALLOWED]
    from tests.test_app import post
    r = post(adm, "/measurements/preview?lang=en", dict(modality="photon", beam_id="1", calibration_id="1", mu="0"))
    assert not [t for t in i18n.leftovers(r.text) if t not in ALLOWED]


# --------------------------------------------------------------------------- no internet needed
def test_pages_load_no_script_or_style_from_the_internet_and_static_files_are_served(pages, client):
    from fastapi.testclient import TestClient
    from app.main import app
    external = re.compile(r'(?:src|href)="(https?://[^"]+)"')
    bad = {}
    for url, r in pages.items():
        if "text/html" in r.headers.get("content-type", ""):
            found = [u for u in external.findall(r.text) if not u.startswith(("https://doi.org", "https://github.com", "https://www.docker.com"))]
            if found:
                bad[url] = found
    assert not bad, bad
    anonymous = TestClient(app, follow_redirects=False)            # the scripts are needed on the sign-in page too
    for name, marker in (("htmx.min.js", "htmx"), ("plotly.min.js", "plotly.js v2.35.2")):
        r = anonymous.get(f"/static/{name}")
        assert r.status_code == 200 and marker in r.text[:2000], name
