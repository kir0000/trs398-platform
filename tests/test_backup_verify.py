"""Every backup is read back after it is made; the database file is checked at the start; a damaged file is shown on every page and does not
block its own restoring."""
import gzip
import sqlite3
import sys
from pathlib import Path

import pytest

from app import backups, db, health
from tests.test_app import client, world  # noqa: F401  (fixtures are discovered here)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def places(tmp_path, monkeypatch):
    data, main = tmp_path / "data", tmp_path / "main"
    data.mkdir()
    main.mkdir()
    monkeypatch.setenv("TRS_DATA", str(data))
    monkeypatch.setenv("TRS_DB", str(data / "trs398.db"))
    monkeypatch.setenv("BACKUP_DIR", str(main))
    monkeypatch.delenv("BACKUP_COPY_DIR", raising=False)
    c = db.connect(data / "trs398.db")
    db.migrate(c)
    c.execute("INSERT INTO linacs(name) VALUES ('TrueBeam')")
    c.commit()
    c.close()
    health._state.update(ok=True, message="", checked=None)
    yield data, main
    health._state.update(ok=True, message="", checked=None)


def test_verify_accepts_a_good_backup_and_rejects_broken_ones(places, tmp_path):
    data, main = places
    good = backups.make()
    r = backups.verify(good)
    assert r == {"ok": True, "measurements": 0, "error": None}
    bad = tmp_path / "bad.db.gz"
    bad.write_bytes(gzip.compress(b"this is not a database at all"))
    assert backups.verify(bad)["ok"] is False
    cut = tmp_path / "cut.db.gz"
    cut.write_bytes(good.read_bytes()[:40])                                         # a truncated file
    assert backups.verify(cut)["ok"] is False
    assert backups.verify(tmp_path / "missing.db.gz")["ok"] is False
    plain = tmp_path / "plain.db.gz"
    plain.write_bytes(b"not gzip")
    assert backups.verify(plain)["ok"] is False


def test_every_new_backup_is_checked_and_the_result_is_kept_for_the_pages(places):
    data, main = places
    made = backups.make()
    st = backups.verify_status(made.name)
    assert st["ok"] is True and st["measurements"] == 0 and st["name"] == made.name
    assert backups.verify_status("another.db.gz") is None
    info = backups.latest()
    assert info["verified"]["ok"] is True and info["name"] == made.name


def test_a_backup_that_cannot_be_read_back_is_removed_and_reported(places, monkeypatch):
    data, main = places
    monkeypatch.setattr(backups, "verify", lambda p: {"ok": False, "measurements": None, "error": "malformed"})
    with pytest.raises(OSError, match="did not pass the check"):
        backups.make()
    assert list(main.glob("trs398_*.db.gz")) == []                                   # nothing bad is kept
    assert backups.request_now() is False                                            # the button of the administrator reports a failure
    assert backups.verify_status()["ok"] is False


def test_the_check_of_the_live_file(places):
    data, main = places
    assert health.check()["ok"] is True and health.problem() == ""
    (data / "trs398.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100 + b"garbage" * 500)       # a damaged file
    r = health.check()
    assert r["ok"] is False and health.problem() and r["checked"] is not None
    (data / "trs398.db").unlink()                                                      # a missing file is a problem as well
    assert health.check()["ok"] is False


def test_the_banner_is_shown_on_every_page_while_the_file_is_damaged(world, client, monkeypatch):
    monkeypatch.setitem(health._state, "ok", False)
    monkeypatch.setitem(health._state, "message", "database disk image is malformed")
    for who in ("adm", "phys", "view"):
        html = world[who].get("/measurements").text
        assert "Файл базы данных повреждён" in html and "database disk image is malformed" in html and "Не вносите данные" in html
    html = world["adm"].get("/about").text
    assert "Файл базы повреждён: database disk image is malformed" in html
    world["adm"].get("/lang/en")
    try:
        en = world["adm"].get("/measurements").text
        assert "The database file is damaged" in en and "Do not enter data" in en
    finally:
        world["adm"].get("/lang/ru")


def test_the_pages_report_a_healthy_file_and_the_check_of_the_backup(world, client, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    backups.make()
    health.check()
    html = world["adm"].get("/admin/backups").text
    assert "Копия проверена: читается, измерений в ней" in html
    assert "Файл базы проверен при запуске: целостность в порядке" in world["adm"].get("/about").text
    old = tmp_path / "bk" / "trs398_2020-01-01_020000.db.gz"
    old.write_bytes(gzip.compress(b"x"))
    import os
    os.utime(old, (9_999_999_999, 9_999_999_999))                                     # the newest by time, made "before the checks existed"
    assert "без проверки чтения" in world["adm"].get("/admin/backups").text


def test_a_damaged_database_does_not_block_its_own_restore(places, tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import restore
    data, main = places
    good = backups.make()
    target = data / "trs398.db"
    target.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)                         # the live file is damaged
    monkeypatch.setattr(sys, "argv", ["restore", str(good), "--yes"])
    restore.main()
    c = sqlite3.connect(target)
    assert [r[0] for r in c.execute("SELECT name FROM linacs")] == ["TrueBeam"]
    c.close()
    kept = list((main / "keep").glob("trs398_damaged_*.db"))
    assert len(kept) == 1                                                                # the damaged file is kept as it was
