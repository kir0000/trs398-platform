"""Restoring the database from the web page «Копии»: the preview, the checks, the safety copy, the sessions, the maintenance mode."""
import gzip
import shutil
import sqlite3

import pytest

from app import backups, restore
from tests import sqlcompat
from tests.sqlcompat import dict_row
from tests.test_app import ADMIN_PW, client, create_measurement, login, post, q, world  # noqa: F401  (fixtures are discovered here)

PAGE = "/admin/backups/restore"


@pytest.fixture()
def folders(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    return tmp_path / "backups"


def measurements(client_):
    return q(client_, "SELECT count(*) FROM measurement_sessions")[0][0]


def make_copy(folders_):
    folders_.mkdir(parents=True, exist_ok=True)
    return backups.make(folder=folders_)


def form(name, **over):
    d = {"name": name, "reason": "возврат к состоянию до ошибки", "password": ADMIN_PW, "confirmation": "ВОССТАНОВИТЬ"}
    d.update(over)
    return d


def test_the_page_shows_what_would_be_lost_and_is_for_the_administrator_only(world, folders):
    copy = make_copy(folders)
    create_measurement(world, "phys")                                          # a record that the copy does not have
    page = world["adm"].get(PAGE, params={"name": copy.name})
    assert page.status_code == 200 and "Всё, что внесено после этой копии, пропадёт" in page.text and copy.name in page.text
    for who in ("phys", "rev", "view"):
        assert world[who].get(PAGE, params={"name": copy.name}).status_code == 403
        assert post(world[who], PAGE, form(copy.name), page="/measurements").status_code == 403


def test_only_files_of_the_backups_are_accepted(world, folders):
    make_copy(folders)
    for bad in ("../secret.key", "trs398.db", "keep/../trs398.db.gz", "other.db.gz", ""):
        assert world["adm"].get(PAGE, params={"name": bad}).status_code == 404


def test_restore_replaces_the_data_makes_a_safety_copy_and_ends_the_sessions(world, folders, client):
    copy = make_copy(folders)
    before = measurements(client)
    create_measurement(world, "phys")
    assert measurements(client) == before + 1
    r = post(world["adm"], PAGE, form(copy.name), page=f"{PAGE}?name={copy.name}")
    assert r.status_code == 200 and "База восстановлена" in r.text
    assert measurements(client) == before                                       # what came after the copy is gone
    saved = list((folders / "keep").glob("trs398_before_restore_*.db.gz"))
    assert len(saved) == 1 and backups.verify(saved[0])["measurements"] == before + 1      # and it can be brought back
    rows = q(client, "SELECT action, details FROM audit_log WHERE action = 'restore'")
    assert rows and "web" in str(rows[-1][1]) and copy.name in str(rows[-1][1])
    again = world["adm"].get("/admin/backups", follow_redirects=False)
    assert again.status_code == 303 and "ended=restored" in again.headers["location"]       # everybody has to sign in again
    restore.mark(0)                                                             # the next tests of the module sign in normally
    world["adm"] = login(client, "admin", ADMIN_PW)


def test_the_wrong_password_the_word_and_the_reason_stop_the_restore(world, folders, client):
    copy = make_copy(folders)
    create_measurement(world, "phys")
    now = measurements(client)
    for bad in (form(copy.name, password="wrong-password"), form(copy.name, confirmation="да"), form(copy.name, reason="x")):
        assert post(world["adm"], PAGE, bad, page=f"{PAGE}?name={copy.name}").status_code == 422
    assert measurements(client) == now and not list((folders / "keep").glob("*")) if (folders / "keep").exists() else True


def test_a_damaged_or_newer_copy_is_refused_before_anything_changes(world, folders, client, tmp_path):
    folders.mkdir(parents=True, exist_ok=True)
    (folders / "trs398_2020-01-01_000000.db.gz").write_bytes(gzip.compress(b"this is not a database" * 50))
    info = restore.preview("trs398_2020-01-01_000000.db.gz")
    assert not info["ok"] and "не читается" in info["problem"].lower() or "поврежд" in info["problem"].lower()
    good = make_copy(folders)                                                   # a copy with a migration this program does not know
    raw = tmp_path / "newer.db"
    raw.write_bytes(gzip.open(good).read())
    c = sqlite3.connect(raw)
    c.execute("INSERT INTO schema_migrations(name) VALUES ('999_from_the_future.sql')")
    c.commit()
    c.close()
    newer = folders / "trs398_2099-01-01_000000.db.gz"
    newer.write_bytes(gzip.compress(raw.read_bytes()))
    assert "более новой" in restore.preview(newer.name)["problem"]
    now = measurements(client)
    r = post(world["adm"], PAGE, form(newer.name), page=f"{PAGE}?name={newer.name}")
    assert r.status_code == 422 and measurements(client) == now


def test_the_maintenance_mode_answers_every_page_but_the_check_of_health(world, folders):
    restore.state.on = True
    try:
        page = world["adm"].get("/measurements")
        assert page.status_code == 503 and "Идёт восстановление базы" in page.text
        assert world["adm"].get("/healthz").status_code == 200
    finally:
        restore.state.on = False
    assert world["adm"].get("/measurements").status_code == 200


def test_a_copy_of_an_older_version_is_brought_up_to_date(world, folders, client, tmp_path):
    """The restore applies the migrations that the copy has not seen (here the copy lacks the last one)."""
    good = make_copy(folders)
    raw = tmp_path / "old.db"
    raw.write_bytes(gzip.open(good).read())
    c = sqlite3.connect(raw)
    last = c.execute("SELECT name FROM schema_migrations ORDER BY name DESC LIMIT 1").fetchone()[0]
    c.execute("DELETE FROM schema_migrations WHERE name = ?", (last,))
    c.commit()
    c.close()
    old = folders / "trs398_2021-01-01_000000.db.gz"
    old.write_bytes(gzip.compress(raw.read_bytes()))
    assert restore.preview(old.name)["upgrade"] == [last]
