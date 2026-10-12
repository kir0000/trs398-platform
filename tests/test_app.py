"""End-to-end tests of the web app against a throw-away database (trs398_test) on the running Postgres.

Skipped automatically when the database container is not reachable. The working database is never touched.
"""
import os
import re
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_DB = "trs398_test"
ADMIN_PW, PHYS_PW, REV_PW, VIEW_PW = "admin-password-1", "physicist-pw-1", "reviewer-pw-1", "viewer-pw-12"


def read_env():
    env = {k: os.environ[k] for k in ("TRS_OWNER_PASSWORD", "TRS_APP_PASSWORD", "TRS_READONLY_PASSWORD")
           if k in os.environ}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


@pytest.fixture(scope="module")
def client():
    env = read_env()
    host = os.environ.get("TRS_TEST_DB_HOST", "127.0.0.1:5433")
    owner_url = f"postgresql://trs_owner:{env.get('TRS_OWNER_PASSWORD', '')}@{host}"
    try:
        admin = psycopg.connect(owner_url + "/postgres", autocommit=True, connect_timeout=3)
    except Exception as e:                                           # pragma: no cover
        pytest.skip(f"Postgres not reachable: {e}")
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    with psycopg.connect(owner_url + f"/{TEST_DB}", autocommit=True) as conn:
        for f in sorted((ROOT / "db" / "init").glob("*.sql")):
            conn.execute(f.read_text(encoding="utf-8"))
    os.environ["DATABASE_URL"] = f"postgresql://trs_app:{env['TRS_APP_PASSWORD']}@{host}/{TEST_DB}"
    os.environ["SESSION_SECRET"] = "test-secret-not-for-production"
    os.environ["BOOTSTRAP_ADMIN_LOGIN"] = "admin"
    os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = ADMIN_PW
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, follow_redirects=False) as c:
        c.owner_url = owner_url + f"/{TEST_DB}"
        c.app_url = os.environ["DATABASE_URL"]
        yield c
    admin = psycopg.connect(owner_url + "/postgres", autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.close()


def token(c, path="/login"):
    html = c.get(path).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def login(c, name, pw):
    from fastapi.testclient import TestClient
    from app.main import app
    s = TestClient(app, follow_redirects=False)
    s.__enter__()
    r = s.post("/login", data={"login": name, "password": pw, "csrf": token(s)})
    assert r.status_code == 303, r.text
    return s


def post(s, path, data=None, page="/measurements", **kw):
    d = dict(data or {})
    d["csrf"] = token(s, page)
    return s.post(path, data=d, **kw)


def q(c, sql, *args):
    with psycopg.connect(c.owner_url) as conn:
        return conn.execute(sql, args).fetchall()


PHOTON = dict(modality="photon", measured_on="2026-09-19", geometry="SSD", mu="200", pressure="100.63", temp="23",
              v1="-300", v2="-100", m1="24.36 24.36 24.36", m2="24.21 24.21 24.21", m_plus="24.35 24.35 24.35",
              m_minus="24.36 24.36 24.36", pdd10="63.3", pdd_zref="63.3", t0="22")


@pytest.fixture(scope="module")
def world(client):
    """Admin sets up users, a linac, a beam and a calibrated chamber."""
    adm = login(client, "admin", ADMIN_PW)
    for login_name, role, pw in (("phys", "physicist", PHYS_PW), ("rev", "reviewer", REV_PW),
                                 ("view", "viewer", VIEW_PW)):
        r = post(adm, "/admin/users", dict(action="create", login=login_name, full_name=login_name.title(),
                                           role=role, password=pw), page="/measurements")
        assert r.status_code == 303
    assert post(adm, "/equipment/linac", dict(name="TrueBeam"), page="/measurements").status_code == 303
    linac_id = q(client, "SELECT id FROM linacs WHERE name='TrueBeam'")[0][0]
    assert post(adm, "/equipment/beam", dict(linac_id=linac_id, modality="photon", energy="6", fff="1"),
                page="/measurements").status_code == 303
    chamber_id = q(client, "SELECT id FROM chambers WHERE name='Sun Nuclear SNC600c Farmer'")[0][0]
    assert post(adm, "/equipment/calibration", dict(chamber_id=chamber_id, serial_no="123456789", nd_w="0.05138",
                                                    k_elec="1", calibrated_on="2026-02-01"),
                page="/measurements").status_code == 303
    beam_id = q(client, "SELECT id FROM beams")[0][0]
    cal_id = q(client, "SELECT id FROM calibrations")[0][0]
    return dict(adm=adm, beam_id=beam_id, cal_id=cal_id, phys=login(client, "phys", PHYS_PW),
                rev=login(client, "rev", REV_PW), view=login(client, "view", VIEW_PW))


def create_measurement(w, who="phys", **over):
    d = dict(PHOTON, beam_id=w["beam_id"], calibration_id=w["cal_id"])
    d.update(over)
    r = post(w[who], "/measurements/new?modality=photon", d, page="/measurements") \
        if False else post(w[who], "/measurements", d, page="/measurements")
    return r


# ----------------------------------------------------------------------------- login and roles
def test_unauthenticated_user_is_sent_to_login(client):
    r = client.get("/measurements")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_wrong_password_is_rejected_and_audited(client):
    r = client.post("/login", data={"login": "admin", "password": "nope-nope-nope", "csrf": token(client)})
    assert r.status_code == 401
    assert q(client, "SELECT count(*) FROM audit_log WHERE action='login_failed'")[0][0] >= 1


def test_post_without_csrf_token_is_forbidden(world):
    r = world["phys"].post("/measurements", data=dict(PHOTON, beam_id=world["beam_id"], calibration_id=world["cal_id"]))
    assert r.status_code == 403


def test_viewer_cannot_create_but_can_read(world):
    v = world["view"]
    assert v.get("/measurements").status_code == 200
    assert v.get("/measurements/new?modality=photon").status_code == 403
    assert create_measurement(world, "view").status_code == 403


def test_non_admin_cannot_open_admin_pages(world):
    for who in ("phys", "rev", "view"):
        for path in ("/admin/users", "/admin/purge", "/admin/audit"):
            assert world[who].get(path).status_code == 403, (who, path)


# ----------------------------------------------------------------------------- calculation through the web form
def test_created_measurement_matches_worksheet(world, client):
    r = create_measurement(world)
    assert r.status_code == 303
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    dw, dev = q(client, "SELECT dw_zmax, deviation_pct FROM results WHERE session_id=%s", sid)[0]
    assert float(dw) == pytest.approx(0.010001263894416275, rel=1e-8)
    assert float(dev) == pytest.approx(0.012638944162750299, rel=1e-6)
    assert "0,010001" in world["phys"].get(f"/measurements/{sid}").text


def test_live_preview_returns_result(world):
    d = dict(PHOTON, beam_id=world["beam_id"], calibration_id=world["cal_id"])
    html = post(world["phys"], "/measurements/preview", d, page="/measurements").text
    assert "0,010001" in html


def test_form_follows_the_worksheet_order_and_has_hints(world):
    html = world["phys"].get("/measurements/new?modality=photon").text
    order = ["1. Радиотерапевтическое оборудование", 'name="tpr"', "2. Ионизационная камера", 'id="calibration_id"',
             "3. Показания дозиметра", 'name="m1"', 'name="m_plus"', "Коррекция рекомбинации", 'name="v1"', 'name="m2"',
             "4. Мощность поглощённой дозы", "5. Мощность поглощённой дозы в воде на глубине максимума"]
    pos = [html.index(t) for t in order]
    assert pos == sorted(pos), "sections are out of the worksheet order"
    assert html.count('class="q"') >= 20                                   # a ? on every non-obvious field
    assert "Таблица 16 охватывает 0,56–0,82" in html and "kvol = 1 + (0,0062·TPR20,10 − 0,0036)" in html
    assert 'data-wallm="' in html and 'data-nd="0.05138"' in html          # chamber details for the selected calibration
    # worksheet-style controls: check boxes for polarity, geometry and beam type, coloured cells
    for name in ("geometry", "pulsed_scanned"):
        assert f'type="radio" name="{name}"' in html
    for cell in ("pc_plus", "pc_minus", "pu_plus", "pu_minus"):                    # polarity comes from the equipment
        assert f'id="{cell}"' in html
    for cell in ("live_ktp", "live_kpol", "live_ks", "live_kvol", "live_kq", "live_mq", "live_dwref", "live_dwmax"):
        assert f'id="{cell}"' in html
    assert "keyup delay:700ms, load" in html


def test_electron_form_has_its_own_fields_in_order(world):
    html = world["phys"].get("/measurements/new?modality=electron").text
    order = ["1. Радиотерапевтическое оборудование", 'name="r50"', 'id="live_r50w"', "2. Ионизационная камера",
             'id="e_r50q0"', "3. Фантом", 'id="e_cpl"', "4. Показания дозиметра",
             "5. Мощность поглощённой дозы в воде на референсной", "6. Мощность поглощённой дозы в воде на глубине"]
    pos = [html.index(t) for t in order]
    assert pos == sorted(pos)
    assert 'name="tpr"' not in html and 'id="live_kvol"' not in html


def _preview(world, **over):
    d = dict(PHOTON, beam_id=world["beam_id"], calibration_id=world["cal_id"])
    d.update(over)
    return post(world["phys"], "/measurements/preview", d, page="/measurements").text


def test_live_cells_fill_in_as_the_form_is_completed(world):
    full = _preview(world)
    assert 'hx-swap-oob="true"' in full
    cell = lambda html, name: re.search(rf'id="live_{name}"[^>]*>([^<]*)<', html).group(1)
    assert cell(full, "ktp") == "1,0103" and cell(full, "ks") == "1,0030" and cell(full, "kvol") == "1,0012"
    assert cell(full, "kq") == "0,9973" and cell(full, "dwmax") == "0,010001" and cell(full, "kpol") == "0,9998"
    assert cell(full, "q") == "0,6276" and cell(full, "m1avg") == "24,3600"
    # only pressure and temperature entered: kTP shows, the dependent cells stay empty and no error is thrown
    part = _preview(world, m1="", m2="", m_plus="", m_minus="", v1="", v2="", mu="", pdd10="", pdd_zref="")
    assert cell(part, "ktp") == "1,0103" and cell(part, "ks") == "—" and cell(part, "dwmax") == "—"
    # a typo in one field does not blank the others
    typo = _preview(world, v1="24,36 24,36")
    assert cell(typo, "ktp") == "1,0103" and "не число" in typo and cell(typo, "dwmax") == "—"
    # cleared fields reset their cells
    assert cell(_preview(world, pressure=""), "ktp") == "—"


def test_invalid_input_is_shown_not_saved(world, client):
    before = q(client, "SELECT count(*) FROM measurement_sessions")[0][0]
    r = create_measurement(world, pdd10="99", pdd_zref="63.3")             # TPR far outside Table 16
    assert r.status_code == 422 and "TPR" in r.text
    assert create_measurement(world, mu="abc").status_code == 422
    assert create_measurement(world, v1="-100", v2="-300").status_code == 422
    assert q(client, "SELECT count(*) FROM measurement_sessions")[0][0] == before


# ----------------------------------------------------------------------------- review workflow
def test_two_person_rule_and_workflow(world, client):
    sid = int(create_measurement(world).headers["location"].rsplit("/", 1)[1])
    phys, rev, adm = world["phys"], world["rev"], world["adm"]
    page = f"/measurements/{sid}"

    assert post(phys, f"{page}/approve", page=page).status_code == 403          # physicist is not a reviewer
    assert post(rev, f"{page}/approve", page=page).status_code == 409           # still a draft
    assert post(phys, f"{page}/submit", page=page).status_code == 303
    assert post(phys, f"{page}/approve", page=page).status_code == 403
    assert post(rev, f"{page}/return", {"comment": ""}, page=page).status_code == 422   # comment required
    assert post(rev, f"{page}/return", {"comment": "перепроверьте давление"}, page=page).status_code == 303
    assert q(client, "SELECT status FROM measurement_sessions WHERE id=%s", sid)[0][0] == "returned"
    assert "перепроверьте давление" in phys.get(page).text

    assert post(phys, f"{page}/submit", page=page).status_code == 303
    assert post(rev, f"{page}/approve", {"comment": "ok"}, page=page).status_code == 303
    assert q(client, "SELECT status FROM measurement_sessions WHERE id=%s", sid)[0][0] == "approved"

    # approved records are immutable from the app
    assert phys.get(f"{page}/edit").status_code == 403
    assert post(phys, f"{page}/edit", dict(PHOTON, beam_id=world["beam_id"], calibration_id=world["cal_id"]),
                page=page).status_code == 403

    # supersede is for those who can edit (physicist/admin); the reviewer approves the copy, so it cannot be a dead end
    assert post(rev, f"{page}/supersede", {"reason": "опечатка в показаниях"}, page=page).status_code == 403
    assert "Заменить" not in rev.get(page).text and "Заменить" in phys.get(page).text
    assert post(phys, f"{page}/supersede", {"reason": "ab"}, page=page).status_code == 422
    r = post(phys, f"{page}/supersede", {"reason": "опечатка в показаниях"}, page=page)
    new_id = int(r.headers["location"].split("/")[2])
    npage = f"/measurements/{new_id}"
    assert r.headers["location"] == f"{npage}/edit" and phys.get(f"{npage}/edit").status_code == 200
    assert q(client, "SELECT status, supersedes_id FROM measurement_sessions WHERE id=%s", new_id)[0] == ("draft", sid)
    assert post(phys, f"{npage}/submit", page=npage).status_code == 303
    assert post(phys, f"{npage}/approve", page=npage).status_code == 403             # not the author's job
    assert post(rev, f"{npage}/approve", {"comment": "исправлено"}, page=npage).status_code == 303
    assert q(client, "SELECT status FROM measurement_sessions WHERE id=%s", sid)[0][0] == "superseded"
    # admin acts as the author of the copy path: submit own, cannot approve own
    assert post(adm, "/measurements", dict(PHOTON, beam_id=world["beam_id"], calibration_id=world["cal_id"]),
                page="/measurements").status_code == 303
    own = int(q(client, "SELECT max(id) FROM measurement_sessions")[0][0])
    assert post(adm, f"/measurements/{own}/submit", page=f"/measurements/{own}").status_code == 303
    assert post(adm, f"/measurements/{own}/approve", page=f"/measurements/{own}").status_code == 403


def test_replacing_a_record_without_extra_fields_opens_a_filled_form(world, client):
    """Records from the demo seeder keep their data in columns only: the form of the replacement must still be filled."""
    import json
    phys, rev = world["phys"], world["rev"]
    uid = lambda login: q(client, "SELECT id FROM users WHERE login=%s", login)[0][0]
    with psycopg.connect(client.owner_url) as conn:
        sid = conn.execute("""INSERT INTO measurement_sessions(measured_on, beam_id, calibration_id, geometry, mu, pressure_kpa,
            temp_c, humidity_pct, v1, v2, m1_readings, m2_readings, m_plus_readings, m_minus_readings, beam_quality, pdd_zref,
            note, status, created_by, approved_by, approved_at, extra)
            VALUES ('2026-08-15', %s, %s, 'SSD', 200, 100.63, 23, 45, -300, -100, '{24.36,24.36,24.36}', '{24.21,24.21,24.21}',
                    '{24.35,24.35,24.35}', '{24.36,24.36,24.36}', 0.62763, 63.3, 'DEMO', 'approved', %s, %s, now(), %s)
            RETURNING id""", (world["beam_id"], world["cal_id"], uid("rev"), uid("phys"),
                              json.dumps({"demo": True, "form": {"pdd10": "63,3"}}))).fetchone()[0]
    page = f"/measurements/{sid}"
    assert "100,63" in phys.get(page).text                                       # the detail page shows the data
    r = post(phys, f"{page}/supersede", {"reason": "уточнение показаний"}, page="/measurements")
    assert r.status_code == 303
    edit_url = r.headers["location"]
    html = phys.get(edit_url).text
    value = lambda name: re.search(rf'name="{name}"[^>]*value="([^"]*)"', html).group(1)
    assert (value("mu"), value("pressure"), value("temp"), value("humidity")) == ("200", "100,63", "23", "45")
    assert (value("v1"), value("v2")) == ("-300", "-100")
    assert (value("m1"), value("m2")) == ("24,36 24,36 24,36", "24,21 24,21 24,21")
    assert (value("m_plus"), value("m_minus"), value("pdd_zref"), value("pdd10")) == ("24,35 24,35 24,35", "24,36 24,36 24,36", "63,3", "63,3")
    assert value("tpr") == ""                                                    # TPR stays derived from the PDD that is filled
    assert re.search(r'type="radio" name="geometry" value="SSD" checked', html)
    # the filled form can be saved as it is, and the result reproduces the original
    fields = {n: value(n) for n in ("mu", "pressure", "temp", "humidity", "v1", "v2", "m1", "m2", "m_plus", "m_minus",
                                    "pdd_zref", "pdd10")}
    new_id = int(edit_url.split("/")[2])
    saved = post(phys, edit_url, dict(fields, modality="photon", measured_on="2026-08-15", beam_id=world["beam_id"],
                                      calibration_id=world["cal_id"], geometry="SSD"), page="/measurements")
    assert saved.status_code == 303
    assert float(q(client, "SELECT dw_zmax FROM results WHERE session_id=%s", new_id)[0][0]) == pytest.approx(0.010001, rel=2e-3)


def test_only_the_author_can_edit_a_draft(world):
    sid = int(create_measurement(world).headers["location"].rsplit("/", 1)[1])
    assert world["adm"].get(f"/measurements/{sid}/edit").status_code == 403
    assert world["phys"].get(f"/measurements/{sid}/edit").status_code == 200


# ----------------------------------------------------------------------------- printing and trends
def test_print_protocol_marks_unapproved_and_shows_values(world, client):
    sid = int(create_measurement(world).headers["location"].rsplit("/", 1)[1])
    short = world["phys"].get(f"/measurements/{sid}/print").text                          # default: one-page summary
    assert "Приложение. Оценка неопределённости (кратко)" in short and "Решение о перекалибровке" not in short
    assert "Этап 2. Пучок фотонов пользователя" not in short and "Примечания к таблице 17" not in short
    assert "Приложение. Оценка неопределённости" not in world["phys"].get(f"/measurements/{sid}/print?unc=none").text
    html = world["phys"].get(f"/measurements/{sid}/print?unc=full").text
    assert "НЕ УТВЕРЖДЕНО" in html and "0,010001" in html and "SNC600c" in html and "TRS-398 Rev.1" in html
    assert "1. Радиотерапевтическое оборудование" in html and "5. Мощность поглощённой дозы" in html.replace("поглощенной", "поглощённой")
    assert "Приложение. Оценка неопределённости" in html and "Решение о перекалибровке" in html   # appendix from the beam history
    assert "Этап 2. Пучок фотонов пользователя" in html and "Примечания к таблице 17" in html
    approved = q(client, "SELECT id FROM measurement_sessions WHERE status='approved' LIMIT 1")[0][0]
    assert "НЕ УТВЕРЖДЕНО" not in world["phys"].get(f"/measurements/{approved}/print").text


def test_trends_show_legacy_and_measured_points(world, client):
    beam_id = world["beam_id"]
    import json
    fixture = ROOT / "tests" / "data" / "photon_journal.json"
    if fixture.exists():
        entries = json.loads(fixture.read_text(encoding="utf-8"))
    else:                                  # synthetic series with one clear outlier
        entries = [{"date": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}", "deviation_pct": 0.1 * ((-1) ** i),
                    "dw_zmax": 0.01} for i in range(30)]
        entries[20]["deviation_pct"] = 3.0
    with psycopg.connect(client.owner_url) as conn:
        for e in entries:
            conn.execute("""INSERT INTO legacy_journal(beam_id, measured_on, deviation_pct, dw_zmax, source_file)
                            VALUES (%s, %s, %s, %s, 't') ON CONFLICT DO NOTHING""",
                         (beam_id, e["date"], e["deviation_pct"], e["dw_zmax"]))
    html = world["view"].get(f"/trends?beam_id={beam_id}").text
    assert "<svg" in html and "за 3σ" in html


def test_only_admin_sets_spc_baseline(world):
    d = dict(beam_id=world["beam_id"], from_date="2023-10-01", to_date="2024-06-30")
    assert post(world["rev"], "/trends/baseline", d, page="/measurements").status_code == 403
    assert post(world["adm"], "/trends/baseline", d, page="/measurements").status_code == 303
    assert "Начало отрезка" in world["view"].get(f"/trends?beam_id={world['beam_id']}").text


# ----------------------------------------------------------------------------- uncertainty
def test_uncertainty_page_photon_uses_journal_sigma(world):
    html = world["view"].get(f"/uncertainty?beam_id={world['beam_id']}").text
    assert "Этап 1. Поверочная лаборатория" in html and "<i>U</i> (<i>k</i> = 2)" in html
    assert "Решение о перекалибровке" in html and "Plotly.newPlot" in html
    assert "<td>1,25</td>" in html and "<td>1.25</td>" not in html       # Type B value of the calibration stage: a comma on Russian pages
    assert "прямоугольное" in html and "Как определяется (формула)" in html and "u = a / √3" in html     # distribution and formula columns


def test_uncertainty_page_electron_depends_on_chamber_and_r50(world, client):
    linac_id = q(client, "SELECT id FROM linacs WHERE name='TrueBeam'")[0][0]
    assert post(world["adm"], "/equipment/beam", dict(linac_id=linac_id, modality="electron", energy="15"),
                page="/measurements").status_code == 303
    eb = q(client, "SELECT id FROM beams WHERE modality='electron'")[0][0]
    low = world["view"].get(f"/uncertainty?beam_id={eb}&chamber=PTW+34001+Roos&q0=co60&r50=1.5").text
    high = world["view"].get(f"/uncertainty?beam_id={eb}&chamber=PTW+34001+Roos&q0=co60&r50=3.8").text
    cyl = world["view"].get(f"/uncertainty?beam_id={eb}&chamber=PTW+30013&q0=co60&r50=1.5").text
    assert "повышена для плоскопараллельной камеры" in low
    assert "повышена для плоскопараллельной камеры" not in high and "повышена" not in cyl
    assert "Табл. 24" in low


def test_uncertainty_rejects_bad_parameters(world):
    b = world["beam_id"]
    assert world["view"].get(f"/uncertainty?beam_id={b}&tolerance=abc").status_code == 422
    assert world["view"].get(f"/uncertainty?beam_id={b}&last_cal=31.12.2026").status_code == 422
    assert world["view"].get("/uncertainty?beam_id=99999").status_code == 404
    assert world["view"].get("/uncertainty").status_code == 200


def test_trends_page_has_interactive_chart(world):
    html = world["view"].get(f"/trends?beam_id={world['beam_id']}").text
    assert 'id="plot"' in html and "Plotly.newPlot" in html and 'id="svgchart"' in html
    assert 'id="cusumplot"' in html and '"cusum_plus"' in html and '"h":' in html            # the chart of the CUSUM sums


# ----------------------------------------------------------------------------- equipment edit / delete
def test_equipment_rename_and_delete_rules(world, client):
    adm = world["adm"]
    pg = "/measurements"
    lid = q(client, "SELECT id FROM linacs WHERE name='TrueBeam'")[0][0]

    # only admin may change equipment
    for who in ("phys", "rev", "view"):
        assert post(world[who], f"/equipment/linac/{lid}/rename", dict(name="X"), page=pg).status_code == 403
        assert post(world[who], f"/equipment/linac/{lid}/delete", page=pg).status_code == 403

    # rename, empty and duplicate names
    assert post(adm, f"/equipment/linac/{lid}/rename", dict(name="TrueBeam SN2480", site="РТО"), page=pg).status_code == 303
    assert q(client, "SELECT name, site FROM linacs WHERE id=%s", lid)[0] == ("TrueBeam SN2480", "РТО")
    assert post(adm, f"/equipment/linac/{lid}/rename", dict(name="  "), page=pg).status_code == 422
    assert post(adm, "/equipment/linac", dict(name="Временный"), page=pg).status_code == 303
    tmp = q(client, "SELECT id FROM linacs WHERE name='Временный'")[0][0]
    assert post(adm, f"/equipment/linac/{tmp}/rename", dict(name="TrueBeam SN2480"), page=pg).status_code == 409
    assert post(adm, "/equipment/linac/99999/rename", dict(name="Q"), page=pg).status_code == 404

    # a linac with beams cannot be deleted; the error is a readable HTML page
    r = post(adm, f"/equipment/linac/{lid}/delete", page=pg)
    assert r.status_code == 409 and "есть пучки" in r.text and "<html" in r.text

    # a beam holding data cannot be deleted
    used_beam = world["beam_id"]
    r = post(adm, f"/equipment/beam/{used_beam}/delete", page=pg)
    assert r.status_code == 409 and "Очистка базы" in r.text
    assert q(client, "SELECT count(*) FROM beams WHERE id=%s", used_beam)[0][0] == 1

    # an unused beam and then its empty linac can be deleted
    assert post(adm, "/equipment/beam", dict(linac_id=tmp, modality="photon", energy="9"), page=pg).status_code == 303
    tb = q(client, "SELECT id FROM beams WHERE linac_id=%s", tmp)[0][0]
    assert post(adm, f"/equipment/linac/{tmp}/delete", page=pg).status_code == 409        # still has a beam
    assert post(adm, f"/equipment/beam/{tb}/delete", page=pg).status_code == 303
    assert post(adm, f"/equipment/linac/{tmp}/delete", page=pg).status_code == 303
    assert q(client, "SELECT count(*) FROM linacs WHERE id=%s", tmp)[0][0] == 0
    assert q(client, "SELECT count(*) FROM audit_log WHERE action IN ('rename_linac','delete_beam','delete_linac')")[0][0] >= 3


def test_calibration_delete_rules(world, client):
    adm, pg = world["adm"], "/measurements"
    assert post(adm, f"/equipment/calibration/{world['cal_id']}/delete", page=pg).status_code == 409   # used by measurements
    chamber_id = q(client, "SELECT id FROM chambers WHERE name='Sun Nuclear SNC600c Farmer'")[0][0]
    assert post(adm, "/equipment/calibration", dict(chamber_id=chamber_id, serial_no="SPARE-1", nd_w="0.05",
                                                    calibrated_on="2026-03-01"), page=pg).status_code == 303
    spare = q(client, "SELECT cal.id FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id "
                      "WHERE cu.serial_no='SPARE-1'")[0][0]
    assert post(world["phys"], f"/equipment/calibration/{spare}/delete", page=pg).status_code == 403
    assert post(adm, f"/equipment/calibration/{spare}/delete", page=pg).status_code == 303
    assert q(client, "SELECT count(*) FROM chamber_units WHERE serial_no='SPARE-1'")[0][0] == 0      # orphan unit removed
    assert post(adm, f"/equipment/calibration/{spare}/delete", page=pg).status_code == 404


def test_errors_are_readable_pages_not_json(world):
    r = world["view"].get("/admin/users")
    assert r.status_code == 403
    assert "Нет доступа" in r.text
    body = r.text.split("<main>")[1].split("</main>")[0]
    assert "detail" not in body and not body.lstrip().startswith("{"), body[:200]
    assert world["view"].get("/measurements/999999").status_code == 404


# ----------------------------------------------------------------------------- serial numbers and electrometer
def test_linac_serial_and_electrometer_reach_the_form_and_the_protocol(world, client):
    adm, phys, pg = world["adm"], world["phys"], "/measurements"
    assert post(adm, "/equipment/linac", dict(name="Аппарат SN", model="Elekta Versa HD", serial_no="LIN-777"), page=pg).status_code == 303
    assert q(client, "SELECT model, serial_no FROM linacs WHERE name='Аппарат SN'")[0] == ("Elekta Versa HD", "LIN-777")
    lid = q(client, "SELECT id FROM linacs WHERE name='Аппарат SN'")[0][0]
    assert post(adm, "/equipment/beam", dict(linac_id=lid, modality="photon", energy="6", fff="1"), page=pg).status_code == 303
    bid = q(client, "SELECT id FROM beams WHERE linac_id=%s", lid)[0][0]

    chamber_id = q(client, "SELECT id FROM chambers WHERE name='Sun Nuclear SNC600c Farmer'")[0][0]
    cal = dict(chamber_id=chamber_id, serial_no="CH-55", nd_w="0.05138", calibrated_on="2026-03-01",
               el_model="PTW UNIDOS", el_sn="E-1234", kelec_separate="1", k_elec="0.9995")
    assert post(adm, "/equipment/calibration", dict(cal, el_sn=""), page=pg).status_code == 422        # model without SN
    assert post(adm, "/equipment/calibration", cal, page=pg).status_code == 303
    assert q(client, "SELECT model, serial_no FROM electrometers")[0] == ("PTW UNIDOS", "E-1234")
    cid = q(client, "SELECT cal.id FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id "
                    "WHERE cu.serial_no='CH-55'")[0][0]
    assert q(client, "SELECT kelec_separate FROM calibrations WHERE id=%s", cid)[0][0] is True
    # the same electrometer is reused, not duplicated
    assert post(adm, "/equipment/calibration", dict(cal, serial_no="CH-56"), page=pg).status_code == 303
    assert q(client, "SELECT count(*) FROM electrometers")[0][0] == 1

    lid = q(client, "SELECT id FROM linacs WHERE serial_no = 'LIN-777'")[0][0]
    page = adm.get(f"/equipment?tab=beams&linac={lid}").text
    assert "LIN-777" in page and "Elekta Versa HD" in page
    page = adm.get("/equipment?tab=dosimeters").text
    assert "PTW UNIDOS, SN E-1234" in page and "☑ да" in page

    form = phys.get("/measurements/new?modality=photon").text
    assert 'data-linac="Elekta Versa HD SN LIN-777"' in form and 'data-elsn="E-1234"' in form and 'data-sep="1"' in form
    assert 'id="linac_info"' in form and 'id="el_sn"' in form and 'name="electrometer_sn"' not in form

    r = create_measurement(world, "phys", beam_id=bid, calibration_id=cid)
    assert r.status_code == 303
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    protocol_html = phys.get(f"/measurements/{sid}/print").text
    assert "Elekta Versa HD SN LIN-777" in protocol_html and "PTW UNIDOS" in protocol_html and "E-1234" in protocol_html
    assert "<b>☑</b> да" in protocol_html and "<b>☐</b> нет" in protocol_html               # calibrated separately


def test_header_is_pinned_and_tables_are_sortable(world):
    html = world["adm"].get("/measurements").text
    assert "header{position:sticky;top:0" in html and "table.sortable th{" in html and "position:sticky" in html
    assert '<table class="sortable">' in html and 'data-default="desc"' in html and "function sortBy" in html
    for path in ("/admin/users", "/admin/audit"):
        assert '<table class="sortable">' in world["adm"].get(path).text, path


def test_pages_are_wide(world):
    html = world["phys"].get("/measurements").text
    assert "max-width:1760px" in html


# ----------------------------------------------------------------------------- user management
def test_last_admin_cannot_be_demoted_or_disabled(world, client):
    adm = world["adm"]
    uid = q(client, "SELECT id FROM users WHERE login='admin'")[0][0]
    assert post(adm, "/admin/users", dict(action="set_role", user_id=uid, role="viewer"), page="/measurements").status_code == 409
    assert post(adm, "/admin/users", dict(action="deactivate", user_id=uid), page="/measurements").status_code == 409


def test_deactivated_user_loses_access(world, client):
    uid = q(client, "SELECT id FROM users WHERE login='view'")[0][0]
    assert post(world["adm"], "/admin/users", dict(action="deactivate", user_id=uid), page="/measurements").status_code == 303
    assert world["view"].get("/measurements").status_code == 303
    assert post(world["adm"], "/admin/users", dict(action="activate", user_id=uid), page="/measurements").status_code == 303
    assert world["view"].get("/measurements").status_code == 303          # session was dropped, must log in again
    world["view"] = login(client, "view", VIEW_PW)
    assert world["view"].get("/measurements").status_code == 200


# ----------------------------------------------------------------------------- purge (keep last: destroys data)
def purge(s, **over):
    d = dict(scope="measurements", reason="очистка тестовых данных", password=ADMIN_PW, confirmation="УДАЛИТЬ")
    d.update(over)
    return post(s, "/admin/purge", d, page="/measurements")


def counts(c):
    return q(c, "SELECT (SELECT count(*) FROM measurement_sessions), (SELECT count(*) FROM results), "
                "(SELECT count(*) FROM legacy_journal), (SELECT count(*) FROM users), "
                "(SELECT count(*) FROM audit_log), (SELECT count(*) FROM calibrations)")[0]


def test_purge_is_forbidden_for_everyone_but_admin(world, client):
    before = counts(client)
    for who in ("phys", "rev", "view"):
        assert purge(world[who]).status_code == 403, who
    assert counts(client) == before


def test_purge_needs_confirmation_reason_and_password(world, client):
    before = counts(client)
    adm = world["adm"]
    assert purge(adm, confirmation="удалить").status_code == 422
    assert purge(adm, confirmation="").status_code == 422
    assert purge(adm, reason="no").status_code == 422
    assert purge(adm, password="wrong-password-1").status_code == 422
    assert purge(adm, scope="everything").status_code == 422
    assert counts(client)[:3] == before[:3]
    assert q(client, "SELECT count(*) FROM audit_log WHERE action='purge_denied'")[0][0] >= 1


def test_app_role_cannot_delete_directly(client):
    with psycopg.connect(client.app_url) as conn:
        for table in ("measurement_sessions", "results", "legacy_journal", "audit_log", "users"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"DELETE FROM {table}")
            conn.rollback()


def test_function_refuses_non_admin_actor(client):
    uid = q(client, "SELECT id FROM users WHERE login='phys'")[0][0]
    with psycopg.connect(client.app_url) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="only an active admin"):
            conn.execute("SELECT admin_purge('all', %s, 'попытка обхода')", (uid,))


def test_purge_legacy_only_keeps_measurements(world, client):
    before = counts(client)
    assert before[0] > 0 and before[2] > 0
    assert purge(world["adm"], scope="legacy").status_code == 200
    after = counts(client)
    assert after[2] == 0 and after[0] == before[0] and after[1] == before[1]


def test_purge_measurements_keeps_users_equipment_and_audit(world, client):
    before = counts(client)
    r = purge(world["adm"], scope="measurements")
    assert r.status_code == 200 and "Готово" in r.text
    after = counts(client)
    assert after[0] == 0 and after[1] == 0                      # measurements and results gone
    assert after[3] == before[3] and after[5] == before[5]      # users and calibrations kept
    assert after[4] > before[4]                                 # audit grew (the purge itself is recorded)
    last = q(client, "SELECT details FROM audit_log WHERE action='purge' ORDER BY id DESC LIMIT 1")[0][0]
    assert last["reason"] == "очистка тестовых данных" and last["sessions"] == before[0]


def test_audit_log_survives_purge_all_and_stays_append_only(world, client):
    assert purge(world["adm"], scope="all").status_code == 200
    n = counts(client)[4]
    assert n > 0
    with psycopg.connect(client.owner_url) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("DELETE FROM audit_log")
    assert world["adm"].get("/admin/audit").status_code == 200


# ----------------------------------------------------------------------------- deleting while data exists
def test_deleting_equipment_with_data_is_blocked_and_nothing_is_lost(world, client):
    """Self-contained scenario (runs last because it purges): every step is checked against the database."""
    adm, phys, rev, pg = world["adm"], world["phys"], world["rev"], "/measurements"

    # a linac and a beam that will hold: 2 measurements (one is a replacement copy) and 3 imported journal rows
    assert post(adm, "/equipment/linac", dict(name="Аппарат с данными"), page=pg).status_code == 303
    lid = q(client, "SELECT id FROM linacs WHERE name='Аппарат с данными'")[0][0]
    assert post(adm, "/equipment/beam", dict(linac_id=lid, modality="photon", energy="10"), page=pg).status_code == 303
    bid = q(client, "SELECT id FROM beams WHERE linac_id=%s", lid)[0][0]

    sid = int(create_measurement(world, "phys", beam_id=bid, pdd20="38").headers["location"].rsplit("/", 1)[1])
    assert post(phys, f"/measurements/{sid}/submit", page=pg).status_code == 303
    assert post(rev, f"/measurements/{sid}/approve", page=pg).status_code == 303
    r = post(phys, f"/measurements/{sid}/supersede", {"reason": "замена для проверки очистки"}, page=pg)
    assert r.status_code == 303
    with psycopg.connect(client.owner_url) as conn:
        for i in range(3):
            conn.execute("INSERT INTO legacy_journal(beam_id, measured_on, deviation_pct, dw_zmax, source_file) "
                         "VALUES (%s, %s, 0.1, %s, 't')", (bid, f"2024-0{i + 1}-01", 0.01 + i / 1e6))

    def stats():
        return dict(sessions=q(client, "SELECT count(*) FROM measurement_sessions WHERE beam_id=%s", bid)[0][0],
                    results=q(client, "SELECT count(*) FROM results r JOIN measurement_sessions s ON s.id=r.session_id "
                                      "WHERE s.beam_id=%s", bid)[0][0],
                    legacy=q(client, "SELECT count(*) FROM legacy_journal WHERE beam_id=%s", bid)[0][0],
                    beam=q(client, "SELECT count(*) FROM beams WHERE id=%s", bid)[0][0],
                    linac=q(client, "SELECT count(*) FROM linacs WHERE id=%s", lid)[0][0])
    before = stats()
    assert before == dict(sessions=2, results=2, legacy=3, beam=1, linac=1)

    # 1) the application refuses, says why (with the numbers), and nothing changes
    r = post(adm, f"/equipment/beam/{bid}/delete", page=pg)
    assert r.status_code == 409 and "измерений 2" in r.text and "исторических записей 3" in r.text
    r = post(adm, f"/equipment/linac/{lid}/delete", page=pg)
    assert r.status_code == 409 and "есть пучки" in r.text
    assert stats() == before

    # 2) even a direct DELETE by the application's database role is stopped by foreign keys
    with psycopg.connect(client.app_url) as conn:
        for sql in ("DELETE FROM beams WHERE id=%s", "DELETE FROM linacs WHERE id=%s"):
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                conn.execute(sql, (bid if "beams" in sql else lid,))
            conn.rollback()
    assert stats() == before

    # 3) a calibration used by those measurements cannot be removed either
    assert post(adm, f"/equipment/calibration/{world['cal_id']}/delete", page=pg).status_code == 409

    # 4) purging only the imported rows does not free the beam: the measurements still hold it
    assert purge(adm, scope="legacy").status_code == 200
    after_legacy = stats()
    assert after_legacy["legacy"] == 0 and after_legacy["sessions"] == 2 and after_legacy["results"] == 2
    r = post(adm, f"/equipment/beam/{bid}/delete", page=pg)
    assert r.status_code == 409 and "измерений 2" in r.text and "исторических записей 0" in r.text

    # 5) purging measurements removes the replacement chain (self-reference) and its results without FK errors
    assert q(client, "SELECT count(*) FROM measurement_sessions WHERE supersedes_id IS NOT NULL")[0][0] >= 1
    assert purge(adm, scope="measurements").status_code == 200
    emptied = stats()
    assert emptied["sessions"] == 0 and emptied["results"] == 0 and emptied["beam"] == 1 and emptied["linac"] == 1
    assert q(client, "SELECT count(*) FROM results")[0][0] == 0

    # 6) now the equipment is free: beam first, then the linac; the calibration is deletable too
    assert post(adm, f"/equipment/beam/{bid}/delete", page=pg).status_code == 303
    assert post(adm, f"/equipment/linac/{lid}/delete", page=pg).status_code == 303
    assert stats()["beam"] == 0 and stats()["linac"] == 0
    assert post(adm, f"/equipment/calibration/{world['cal_id']}/delete", page=pg).status_code == 303

    # 7) users and the audit trail are untouched and record every destructive step
    actions = [a[0] for a in q(client, "SELECT action FROM audit_log WHERE action IN "
                                       "('purge','delete_beam','delete_linac','delete_calibration') ORDER BY id")]
    assert actions[-5:] == ["purge", "purge", "delete_beam", "delete_linac", "delete_calibration"]
    assert q(client, "SELECT count(*) FROM users WHERE is_active")[0][0] >= 4

