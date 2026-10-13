"""The second copy of the backups (another disk / network folder): set, written, pruned, reported, and its failures are visible."""
import os
import time

import pytest

from app import backups, settings
from tests.test_app import client, post, world  # noqa: F401  (fixtures are discovered here)


@pytest.fixture()
def places(tmp_path, monkeypatch):
    data, main, second = tmp_path / "data", tmp_path / "main", tmp_path / "second"
    data.mkdir()
    main.mkdir()
    monkeypatch.setenv("TRS_DATA", str(data))
    monkeypatch.setenv("BACKUP_DIR", str(main))
    monkeypatch.delenv("BACKUP_COPY_DIR", raising=False)
    from app import db
    c = db.connect(data / "trs398.db")
    db.migrate(c)
    c.commit()
    c.close()
    return data, main, second


def test_without_a_second_place_nothing_is_copied_and_the_state_says_so(places):
    data, main, second = places
    assert backups.copy_dir() is None and backups.copy_out(main / "x.db.gz") is None
    st = backups.external_status()
    assert st["configured"] is False and st["stale"] is False and "не настроена" in st["message"]


def test_every_new_backup_is_written_to_the_second_place_and_old_ones_are_pruned(places):
    data, main, second = places
    ok, msg = backups.set_copy_dir(str(second))
    assert ok and second.is_dir() and settings.load()["backup_copy_dir"] == str(second)
    first = backups.make()
    assert (second / first.name).exists() and (second / first.name).stat().st_size == first.stat().st_size
    st = backups.external_status()
    assert st["ok"] and st["configured"] and st["name"] == first.name and "свежая" in st["message"]
    old = second / "trs398_2020-01-01_020000.db.gz"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 90 * 86400,) * 2)
    backups.make()
    assert not old.exists()                                           # older than the keeping period
    assert len(list(second.glob("trs398_*.db.gz"))) >= 1


def test_the_safety_copies_of_restore_are_not_copied_out(places, tmp_path):
    data, main, second = places
    backups.set_copy_dir(str(second))
    keep = main / "keep"
    keep.mkdir()
    made = backups.make(folder=keep)
    assert made.exists() and not (second / made.name).exists()


def test_a_failure_is_reported_not_raised(places, monkeypatch):
    data, main, second = places
    backups.set_copy_dir(str(second))
    import shutil

    def boom(*a, **k):
        raise OSError("the disk is not connected")
    monkeypatch.setattr(shutil, "copy2", boom)
    made = backups.make()                                             # the main backup still succeeds
    assert made.exists()
    st = backups.external_status()
    assert st["ok"] is False and st["stale"] is True and "the disk is not connected" in st["message"]


def test_the_folder_is_checked_when_it_is_set(places, tmp_path):
    data, main, second = places
    ok, msg = backups.set_copy_dir(str(main))
    assert not ok and "та же папка" in msg and settings.load()["backup_copy_dir"] == ""
    blocked = tmp_path / "file.txt"
    blocked.write_text("a file, not a folder")
    ok, msg = backups.set_copy_dir(str(blocked / "sub"))
    assert not ok and "нельзя записывать" in msg
    ok, _ = backups.set_copy_dir(str(second))
    assert ok
    ok, msg = backups.set_copy_dir("")
    assert ok and "выключена" in msg and backups.copy_dir() is None


def test_status_becomes_stale_after_36_hours(places):
    import datetime as dt
    data, main, second = places
    backups.set_copy_dir(str(second))
    backups.make()
    assert backups.external_status()["ok"]
    later = dt.datetime.now() + dt.timedelta(hours=40)
    st = backups.external_status(later)
    assert st["ok"] is False and st["stale"] and "старше 36 часов" in st["message"]


def test_the_backups_page_sets_the_second_copy_for_admins_only(world, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "main"))
    second = tmp_path / "second"
    page = "/admin/backups"
    assert world["adm"].get(page).status_code == 200 and "Вторая копия (другое место)" in world["adm"].get(page).text
    assert post(world["phys"], "/admin/backups/external", {"folder": str(second)}, page="/measurements").status_code == 403
    r = post(world["adm"], "/admin/backups/external", {"folder": str(second)}, page=page)
    assert r.status_code == 303 and "extok=1" in r.headers["location"]
    html = world["adm"].get(r.headers["location"]).text
    assert "Папка сохранена" in html and str(second) in html
    r = post(world["adm"], "/admin/backups/external", {"folder": str(tmp_path / "main")}, page=page)
    assert "extok=0" in r.headers["location"]
    post(world["adm"], "/admin/backups/external", {"folder": ""}, page=page)                       # switched off again
