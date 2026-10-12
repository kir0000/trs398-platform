import datetime as dt
import os
import time

from app import backups
from tests.test_app import client, post, world  # noqa: F401  (fixtures are discovered here)


def make(folder, name, hours_old):
    p = folder / name
    p.write_bytes(b"x" * 2048)
    t = time.time() - hours_old * 3600
    os.utime(p, (t, t))


def test_latest_reports_the_newest_dump_and_its_freshness(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    assert backups.latest()["found"] is False and backups.latest()["stale"] is True
    make(tmp_path, "trs398_2026-10-01_020000.sql.gz", 200)
    make(tmp_path, "trs398_2026-10-10_020000.sql.gz", 5)
    make(tmp_path, "other.txt", 1)                                         # unrelated files are ignored
    info = backups.latest()
    assert info["found"] and info["name"] == "trs398_2026-10-10_020000.sql.gz" and info["count"] == 2
    assert info["stale"] is False and info["size_kb"] == 2 and "свежая" in info["message"]
    make(tmp_path, "trs398_2026-10-11_020000.sql.gz", 40)                  # the newest by time is 5 h old, so still fresh
    assert backups.latest()["name"] == "trs398_2026-10-10_020000.sql.gz"
    for f in tmp_path.glob("trs398_2026-10-1*"):
        os.utime(f, (time.time() - 50 * 3600,) * 2)
    assert backups.latest()["stale"] is True and "старше 36 часов" in backups.latest()["message"]
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "missing"))
    assert backups.latest()["found"] is False


def test_the_purge_page_shows_the_state_of_the_backups(world, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    html = world["adm"].get("/admin/purge").text
    assert "Резервная копия" in html and "Резервных копий нет" in html
    make(tmp_path, "trs398_2026-10-11_020000.sql.gz", 3)
    html = world["adm"].get("/admin/purge").text
    assert "trs398_2026-10-11_020000.sql.gz" in html and "Резервная копия свежая" in html
    make(tmp_path, "trs398_2026-10-11_020000.sql.gz", 80)
    assert "старше 36 часов" in world["adm"].get("/admin/purge").text
    # a refused purge still shows the backup state
    d = dict(scope="measurements", reason="x", password="nope", confirmation="")
    r = post(world["adm"], "/admin/purge", d, page="/measurements")
    assert r.status_code == 422 and "Резервная копия" in r.text
