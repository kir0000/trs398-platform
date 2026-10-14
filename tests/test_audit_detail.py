"""The audit log in detail: readable actions and objects, "was -> became", the address, filters, pages, CSV, system events."""
import csv
import io
import json
import re
from pathlib import Path

from app import auditlog, i18n
from tests import sqlcompat
from tests.sqlcompat import dict_row
from tests.test_app import PHOTON, client, create_measurement, post, q, world  # noqa: F401  (fixtures are discovered here)

ROOT = Path(__file__).resolve().parent.parent


def left(html):
    return [t for t in i18n.leftovers(html) if t != "Language / Язык"]


def log(world_, **params):
    return world_["adm"].get("/admin/audit", params=params)


def test_every_action_of_the_program_has_a_name_and_a_group():
    codes = set()
    for f in (ROOT / "app").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        codes |= set(re.findall(r'audit\(\s*conn\s*,\s*[^,]+,\s*"([a-z_]+)"', text))
        codes |= set(re.findall(r'system_event\(\s*"([a-z_]+)"', text))
        codes |= set(re.findall(r"INSERT INTO audit_log\([^)]*\)\s*VALUES \(%s, '([a-z_]+)'", text))
    for f in (ROOT / "tools").glob("*.py"):                                                  # the scripts write records too
        codes |= set(re.findall(r"INSERT INTO audit_log\([^)]*\)\s*VALUES \('([a-z_]+)'", f.read_text(encoding="utf-8")))
    codes |= {"submit", "approve", "return", "activate", "deactivate"}                       # the ones that come from a variable
    missing = sorted(c for c in codes if c not in auditlog.ACTIONS)
    assert not missing, f"actions without a name in app/auditlog.py: {missing}"
    assert all(g in auditlog.GROUPS for _, g in auditlog.ACTIONS.values())


def test_the_life_of_a_record_is_readable_with_the_address_and_the_changes(world, client):
    sid = int(create_measurement(world, "phys").headers["location"].rsplit("/", 1)[1])
    page = f"/measurements/{sid}"
    no = q(client, "SELECT protocol_no FROM measurement_sessions WHERE id=%s", sid)[0][0]
    r = post(world["phys"], f"{page}/edit", dict(PHOTON, beam_id=world["beam_id"], calibration_id=world["cal_id"], mu="250"), page=f"{page}/edit")
    assert r.status_code == 303, r.text[:300]
    assert post(world["phys"], f"{page}/submit", page=page).status_code == 303
    assert post(world["rev"], f"{page}/approve", {"comment": "всё верно"}, page=page).status_code == 303
    world["adm"].get(f"{page}/print")
    assert q(client, "SELECT count(*) FROM audit_log WHERE action='print' AND entity_id=%s", str(sid))[0][0] == 1       # once, not twice
    assert post(world["adm"], f"{page}/void", {"reason": "введено по ошибке"}, page=page).status_code == 303
    html = log(world).text
    for name in ("Создана запись измерения", "Изменена запись измерения", "Отправлено на проверку", "Запись утверждена",
                 "Открыта печатная форма протокола", "Запись аннулирована"):
        assert name in html, name
    assert f"Протокол № {no}" in html and f'href="/measurements/{sid}"' in html           # the object is a link with the number
    assert "MU:" in html and "→" in html and "250" in html                                  # the edit shows what it changed
    assert "введено по ошибке" in html and "всё верно" in html                              # reasons and comments
    assert "testclient" in html                                                              # the address of the computer
    rows = q(client, "SELECT ip FROM audit_log WHERE entity='measurement' AND entity_id=%s", str(sid))
    assert rows and all(r[0] == "testclient" for r in rows)


def test_equipment_and_users_changes_show_was_and_became(world, client):
    adm = world["adm"]
    bid = world["beam_id"]
    params = dict(dose_rate="600", field_size="10 х 10", phantom="водный", c_pl="1", h_pl="1", zmax="1.5", pdd_zref="66.6", tmr_zref="0.7",
                  cal_mu="100", ref_depth="10", window_material="", window_thickness="")
    assert post(adm, f"/equipment/beam/{bid}/params", params, page="/equipment").status_code == 303
    assert post(adm, f"/equipment/beam/{bid}/params", dict(params, dose_rate="1400"), page="/equipment").status_code == 303
    html = log(world, action="beam_params").text
    assert "Мощность дозы, MU/мин:" in html and "600 → 1400" in html
    uid = q(client, "SELECT id FROM users WHERE login='view'")[0][0]
    assert post(adm, "/admin/users", dict(action="set_role", user_id=uid, role="physicist"), page="/admin/users").status_code == 303
    html = log(world, action="set_role").text
    assert "наблюдатель → физик" in html and "Пользователь view" in html
    post(adm, "/admin/users", dict(action="set_role", user_id=uid, role="viewer"), page="/admin/users")


def test_filters_pages_and_csv(world, client):
    with sqlcompat.connect(client.owner_url, row_factory=dict_row) as conn:
        for i in range(230):
            conn.execute("INSERT INTO audit_log(action, entity, entity_id, details, ip) VALUES ('login', 'users', '1', %s, %s)",
                         (json.dumps({"n": i}, ensure_ascii=False), "10.0.0.5"))
        conn.execute("INSERT INTO audit_log(at, action, entity, details) VALUES ('2020-05-05 10:00:00', 'purge', 'purge', %s)",
                     (json.dumps({"reason": "старый тест очистки"}, ensure_ascii=False),))
        conn.commit()
    assert "Страница 1 из" in log(world).text and "Вперёд" in log(world).text
    assert "Страница 2 из" in world["adm"].get("/admin/audit?page=2").text
    html = log(world, **{"from": "2020-05-01", "to": "2020-05-31"}).text                    # a date range
    assert "Очистка" in html and "старый тест очистки" in html and "Найдено записей: 1." in html
    assert "старый тест очистки" in log(world, group="Очистка").text
    assert "Найдено записей: 1." in log(world, q="старый тест").text
    assert log(world, q="10.0.0.5").text.count("10.0.0.5") >= 100                         # search by the address
    adm_id = q(client, "SELECT id FROM users WHERE login='admin'")[0][0]
    assert "Найдено записей: 0." in log(world, user=adm_id, action="purge").text
    r = world["adm"].get("/admin/audit.csv", params={"from": "2020-05-01", "to": "2020-05-31"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "audit.csv" in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf")                                           # Excel reads Cyrillic with the BOM
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:4] == ["Время", "Пользователь", "Адрес", "Действие"] and len(rows) == 2 and "purge" in rows[1]
    assert world["phys"].get("/admin/audit.csv").status_code == 403 and world["phys"].get("/admin/audit").status_code == 403
    assert q(client, "SELECT count(*) FROM audit_log WHERE action='audit_export'")[0][0] >= 1


def test_the_program_writes_its_own_records(client):
    assert q(client, "SELECT count(*) FROM audit_log WHERE action='app_start' AND user_id IS NULL")[0][0] >= 1
    from app import db
    db.system_event("backup_failed", "backups", None, {"error": "disk full"})
    assert q(client, "SELECT details FROM audit_log WHERE action='backup_failed' ORDER BY id DESC LIMIT 1")[0][0] == {"error": "disk full"}
    db.system_event("anything", "system")                                                    # never raises


def test_every_action_is_shown_in_english_without_russian_left(world, client):
    with sqlcompat.connect(client.owner_url, row_factory=dict_row) as conn:
        for code in auditlog.ACTIONS:
            conn.execute("INSERT INTO audit_log(action, entity, entity_id, details, ip) VALUES (%s, 'measurement', '999999', %s, '127.0.0.1')",
                         (code, json.dumps({"reason": "test", "changes": {"mu": ["100", "200"], "fff": [0, 1]}, "ok": True})))
        conn.commit()
    adm = world["adm"]
    adm.get("/lang/en")
    try:
        for page in range(1, 4):
            html = adm.get(f"/admin/audit?page={page}").text
            assert not left(html), left(html)[:5]
    finally:
        adm.get("/lang/ru")


def test_the_upgrade_from_2_0_1_keeps_the_log_and_adds_the_address(tmp_path):
    from app import db
    path = tmp_path / "trs398.db"
    c = db.connect(path)
    c.executescript((ROOT / "tests" / "data" / "001_baseline_v2_0_1.sql").read_text(encoding="utf-8"))
    c.execute("CREATE TABLE schema_migrations(name TEXT PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    c.execute("INSERT INTO schema_migrations(name) VALUES ('001_baseline.sql')")
    c.execute("INSERT INTO audit_log(action, entity, entity_id, details) VALUES ('login', 'users', '1', '{}')")
    c.commit()
    assert db.pending(c)[0] == "002_audit_ip.sql"
    db.migrate(c)
    c.commit()
    assert "ip" in [r["name"] for r in c.execute("PRAGMA table_info(audit_log)").fetchall()]
    assert c.execute("SELECT action, ip FROM audit_log").fetchall() == [{"action": "login", "ip": None}]          # old records keep no address
    c.close()


def test_a_restore_leaves_a_record_after_the_next_start(client, tmp_path, monkeypatch):
    import json as _json
    from app import db
    from app.main import note_restore
    marker = db.data_dir() / "restored.json"
    marker.write_text(_json.dumps({"file": "trs398_2026-10-13_120000.db.gz", "at": "2026-10-13T12:00:00"}), encoding="utf-8")
    note_restore()
    assert not marker.exists()
    details = q(client, "SELECT details FROM audit_log WHERE action='restore' ORDER BY id DESC LIMIT 1")[0][0]
    assert details["file"] == "trs398_2026-10-13_120000.db.gz"
    note_restore()                                                                          # without a marker nothing happens


def test_polish_of_the_readable_records():
    """Details a reader sees: dates as dd.mm.yyyy, from before to, roles as words, no raw keys of the helper scripts, the linac once in a beam."""
    lines = auditlog.details_lines({"to": "2026-10-12", "from": "2025-10-31", "role": "admin", "sessions_removed": 3, "linac_fields": [1, 2]})
    flat = [(k, v) for k, v, _ in lines]
    assert ("С", "31.10.2025") in flat and ("По", "12.10.2026") in flat
    assert flat.index(("С", "31.10.2025")) + 1 == flat.index(("По", "12.10.2026"))                 # from, then to
    names = dict((k, v) for k, v, _ in lines)
    assert names["Роль"] == "администратор" and names["Удалено записей"] == "3" and names["Дополнено полей аппаратов"] == "2"


def test_a_beam_is_named_with_the_linac_once_and_the_uncertainty_by_its_modality(world, client):
    from app import db
    with db.connect(client.owner_url) as conn:
        conn.execute("INSERT INTO audit_log(user_id, action, entity, entity_id, details) VALUES (NULL, 'beam_params', 'beams', %s, '{}')", (str(world["beam_id"]),))
        conn.execute("INSERT INTO audit_log(user_id, action, entity, entity_id, details) VALUES (NULL, 'uncertainty_reset', 'uncertainty', 'electron', '{}')")
    html = log(world, action="beam_params").text
    assert "TrueBeam, TrueBeam" not in html and "TrueBeam, 6 MV FFF" in html
    assert "Неопределённость, электроны" in log(world, action="uncertainty_reset").text


def test_the_load_of_demo_data_is_a_summary_not_a_list_of_database_numbers():
    lines = auditlog.details_lines({"beams": [16, 17, 18], "calibrations": [11, 12], "units": [7], "electrometers": [3], "users": [4, 5],
                                    "linac_fields": [], "beam_fields": [16, 2, 17], "sessions": 504})
    d = {k: v for k, v, _ in lines}
    assert d == {"Создано пучков": "3", "Создано калибровок": "2", "Создано камер": "1", "Создано электрометров": "1",
                 "Создано пользователей": "2", "Дополнено полей пучков": "3", "Записей измерений": "504"}      # an empty list says nothing: left out


def test_a_save_without_changes_says_so():
    assert [(k, v) for k, v, _ in auditlog.details_lines({"changes": {}})] == [("", "Значения не изменились")]
    assert auditlog.details_lines({}) == []                                                                         # no details at all: nothing to say
