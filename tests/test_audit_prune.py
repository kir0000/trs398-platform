"""The controlled clearing of the audit log: the protection stays, the clearing archives first, keeps a safety copy and leaves its own record."""
import csv
import gzip
import hashlib
import io
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from app import auditlog, backups, dbops, db
from tests import sqlcompat
from tests.sqlcompat import dict_row
from tests.test_app import ADMIN_PW, client, post, q, world  # noqa: F401  (fixtures are discovered here)

PAGE = "/admin/audit/clear"


@pytest.fixture()
def folders(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    return tmp_path / "backups"


def old_records(client_, n=5, year=2020):
    with sqlcompat.connect(client_.owner_url, row_factory=dict_row) as conn:
        for i in range(n):
            conn.execute("INSERT INTO audit_log(at, action, entity, entity_id, details) VALUES (%s, 'login', 'users', '1', %s)",
                         (f"{year}-03-{10 + i:02d} 10:00:00", json.dumps({"n": i})))
        conn.commit()


def total(client_):
    return q(client_, "SELECT count(*) FROM audit_log")[0][0]


def form(**over):
    d = {"mode": "older", "days": "30", "reason": "очистка тестовых записей", "password": ADMIN_PW, "confirmation": "ОЧИСТИТЬ"}
    d.update(over)
    return d


def test_the_protection_of_the_log_is_still_in_force(world, client):
    with sqlcompat.connect(client.owner_url) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM audit_log")
        conn.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE audit_log SET action = 'x'")
    assert total(client) > 0


def test_the_page_is_for_the_administrator_only(world, folders):
    assert world["adm"].get(PAGE).status_code == 200 and "Очистка журнала аудита" in world["adm"].get(PAGE).text
    for who in ("phys", "rev", "view"):
        assert world[who].get(PAGE).status_code == 403
        assert post(world[who], PAGE, form(), page="/measurements").status_code == 403


def test_wrong_input_changes_nothing(world, client, folders):
    old_records(client)
    before = total(client)
    for bad, text in ((dict(mode=""), "Выберите, что удалить"), (dict(days="0"), "Сколько дней оставить"), (dict(days="abc"), "Сколько дней оставить"),
                      (dict(confirmation="нет"), "введите слово ОЧИСТИТЬ"), (dict(reason="ок"), "не короче 5 символов"),
                      (dict(password="wrong-password-123"), "Неверный пароль")):
        r = post(world["adm"], PAGE, form(**bad), page=PAGE)
        assert r.status_code == 422 and text in r.text, (bad, r.text[:200])
    assert total(client) == before + 1                                                      # only the record of the wrong password
    assert q(client, "SELECT count(*) FROM audit_log WHERE action='audit_prune_denied'")[0][0] == 1
    assert not (folders / "audit_archive").exists()                                         # no archive, no copy: nothing was done


def test_clearing_old_records_archives_everything_keeps_a_copy_and_writes_its_record(world, client, folders):
    old_records(client, n=5, year=2020)
    before = total(client)
    n_old = q(client, "SELECT count(*) FROM audit_log WHERE at < '2021-01-01'")[0][0]
    assert n_old >= 5
    r = post(world["adm"], PAGE, form(mode="older", days="30"), page=PAGE)
    assert r.status_code == 200 and "Готово." in r.text and f"Удалено записей: {n_old}" in r.text
    assert total(client) == before - n_old + 1                                               # the old ones are gone, the record of the clearing is added
    assert q(client, "SELECT count(*) FROM audit_log WHERE at < '2021-01-01'")[0][0] == 0
    # the archive holds the WHOLE log as it was, with the old records
    archives = list((folders / "audit_archive").glob("audit_*.csv"))
    assert len(archives) == 1
    data = archives[0].read_bytes()
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == before + 1 and rows[0][:4] == ["Время", "Пользователь", "Адрес", "Действие"]
    assert sum(1 for row in rows if row[0].endswith(".2020") or ".03.2020" in row[0]) >= 5
    # the record of the clearing: who, why, how many, the file and its checksum
    rec = q(client, "SELECT details, user_id, ip FROM audit_log WHERE action='audit_pruned'")[0]
    details = rec[0]
    assert details["deleted"] == n_old and details["reason"] == "очистка тестовых записей" and details["archive"] == archives[0].name
    assert details["sha256"] == hashlib.sha256(data).hexdigest() and details["first"] == "2020-03-10" and details["last"] == "2020-03-14"
    assert rec[1] is not None and rec[2] == "testclient"
    # the safety copy of the whole database contains the log before the clearing: the clearing can be undone
    copies = list((folders / "keep").glob("trs398_before_audit_clear_*.db.gz"))
    assert len(copies) == 1 and details["safety_copy"] == copies[0].name
    plain = folders / "check.db"
    plain.write_bytes(gzip.decompress(copies[0].read_bytes()))
    c = sqlite3.connect(plain)
    assert c.execute("SELECT count(*) FROM audit_log").fetchone()[0] == before
    assert c.execute("SELECT count(*) FROM audit_log WHERE at < '2021-01-01'").fetchone()[0] == n_old
    c.close()
    # the protection is back after the clearing
    with sqlcompat.connect(client.owner_url) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM audit_log")
    assert q(client, "SELECT count(*) FROM _maintenance WHERE k='audit_prune'")[0][0] == 0
    page = world["adm"].get("/admin/audit?action=audit_pruned").text
    assert "Журнал аудита очищен" in page and "Удалено записей:" in page and "очистка тестовых записей" in page


def test_records_of_earlier_clearings_are_never_deleted_and_all_means_all_the_rest(world, client, folders):
    old_records(client, n=3, year=2019)
    earlier = q(client, "SELECT count(*) FROM audit_log WHERE action='audit_pruned'")[0][0]
    r = post(world["adm"], PAGE, form(mode="all", confirmation="clear"), page=PAGE)             # the English word is accepted in any case
    assert r.status_code == 200, r.text[:300]
    left = [x[0] for x in q(client, "SELECT action FROM audit_log ORDER BY id")]
    assert left == ["audit_pruned"] * (earlier + 1)                                          # everything else is gone, the clearings stay
    assert q(client, "SELECT json_extract(details, '$.kept') FROM audit_log ORDER BY id DESC LIMIT 1")[0][0] == earlier + 1
    # a second clearing of everything: the first record of a clearing survives
    r = post(world["adm"], PAGE, form(mode="all", reason="ещё раз"), page=PAGE)             # only the clearings are left: nothing to delete
    assert r.status_code == 422 and "Записей старше этого срока нет" in r.text
    assert [x[0] for x in q(client, "SELECT action FROM audit_log")].count("audit_pruned") == earlier + 1


def test_nothing_older_than_the_term_is_reported_not_done(world, client, folders):
    before = total(client)
    r = post(world["adm"], PAGE, form(mode="older", days="3650"), page=PAGE)
    assert r.status_code == 422 and "Записей старше этого срока нет" in r.text
    assert total(client) == before
    assert not (folders / "audit_archive").exists()


def test_dbops_refuses_a_non_admin_a_short_reason_and_a_negative_term(world, client, folders):
    with db.connect(client.owner_url) as conn:
        phys = conn.execute("SELECT id FROM users WHERE login='phys'").fetchone()["id"]
        adm = conn.execute("SELECT id FROM users WHERE login='admin'").fetchone()["id"]
        with pytest.raises(dbops.MaintenanceError, match="admin"):
            dbops.prune_audit(conn, phys, 30, "reason is long enough", folders / "a", folders / "k")
        with pytest.raises(dbops.MaintenanceError, match="reason"):
            dbops.prune_audit(conn, adm, 30, "no", folders / "a", folders / "k")
        with pytest.raises(dbops.MaintenanceError, match="negative"):
            dbops.prune_audit(conn, adm, -1, "reason is long enough", folders / "a", folders / "k")
    assert not (folders / "a").exists()


def test_english_page_and_the_button_on_the_log(world, client, folders):
    adm = world["adm"]
    assert "/admin/audit/clear" in adm.get("/admin/audit").text and "Очистить журнал…" in adm.get("/admin/audit").text
    adm.get("/lang/en")
    try:
        html = adm.get(PAGE).text
        assert "Clearing the audit log" in html and "CLEAR" in html and not [t for t in __import__("app.i18n", fromlist=["x"]).leftovers(html) if t != "Language / Язык"]
    finally:
        adm.get("/lang/ru")


def test_the_migration_is_guarded_and_every_action_has_a_name():
    assert "audit_pruned" in auditlog.ACTIONS and "audit_prune_denied" in auditlog.ACTIONS
    root = Path(__file__).resolve().parent.parent
    assert (root / "app" / "migrations" / "003_audit_prune.sql").exists()
