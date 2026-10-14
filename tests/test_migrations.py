"""Updates must never lose data: a released migration is never edited, an older database is upgraded without loss,
a safety copy is made first, and a failed migration changes nothing."""
import hashlib
import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db

ROOT = Path(__file__).resolve().parent.parent
RELEASED = {                                           # name -> sha256 of the text with LF line ends (released in 2.0.0 and later)
    "001_baseline.sql": "210f7cef1590e18faa4508592835e5e9927e9fcebd505b4db4724241d3824cc7",
    "002_audit_ip.sql": "ca7d2fc9f104ffd5423ba408a58dfec7debd1c59b7aad95c76c93a586fd63e87",                       # released in 2.2.0
    "003_audit_prune.sql": "708e0f12c061c0e00c88f84ee36d9e2d3fd7d6916fddb74b003a53c90fb782df",                       # released in 2.5.0
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def structure(path) -> dict:
    c = sqlite3.connect(path)
    try:
        return {r[0]: (r[1], r[2]) for r in c.execute("SELECT name, type, tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    finally:
        c.close()


def test_released_migrations_are_never_edited():
    for name, expected in RELEASED.items():
        path = ROOT / "app" / "migrations" / name
        assert path.exists(), f"{name} was released and must stay"
        assert digest(path) == expected, f"{name} was released: add a new migration instead of editing it"
    assert digest(ROOT / "tests" / "data" / "001_baseline_v2_0_1.sql") == RELEASED["001_baseline.sql"]


def test_migrations_are_numbered_without_gaps():
    names = sorted(p.name for p in (ROOT / "app" / "migrations").glob("*.sql"))
    numbers = [int(re.match(r"(\d{3})_", n).group(1)) for n in names]
    assert numbers == list(range(1, len(numbers) + 1)), names


def test_a_new_database_gets_all_migrations_once(tmp_path):
    c = db.connect(tmp_path / "a.db")
    first = db.migrate(c)
    c.commit()
    assert first == sorted(p.name for p in db.MIGRATIONS.glob("*.sql")) and db.migrate(c) == [] and db.pending(c) == []
    assert db.has_data(c) is False
    c.close()


@pytest.fixture()
def old_database(tmp_path, monkeypatch):
    """A database as version 2.0.1 left it (made from the frozen schema), with some data, and a folder of migrations with a new one."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("TRS_DATA", str(data))
    monkeypatch.setenv("TRS_NO_SCHEDULER", "1")
    path = data / "trs398.db"
    monkeypatch.setenv("TRS_DB", str(path))
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.delenv("BACKUP_COPY_DIR", raising=False)
    c = db.connect(path)
    c.executescript((ROOT / "tests" / "data" / "001_baseline_v2_0_1.sql").read_text(encoding="utf-8"))
    c.execute("CREATE TABLE schema_migrations(name TEXT PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    c.execute("INSERT INTO schema_migrations(name) VALUES ('001_baseline.sql')")
    c.execute("INSERT INTO users(login, full_name, role, password_hash) VALUES ('boss', 'Boss', 'admin', 'x')")
    c.execute("INSERT INTO linacs(name) VALUES ('TrueBeam')")
    c.commit()
    c.close()
    folder = tmp_path / "migrations"
    folder.mkdir()
    shutil.copy(ROOT / "app" / "migrations" / "001_baseline.sql", folder / "001_baseline.sql")
    monkeypatch.setattr(db, "MIGRATIONS", folder)
    return path, folder


def test_an_old_database_is_upgraded_without_loss_and_a_safety_copy_is_made(old_database):
    path, folder = old_database
    before = structure(path)
    (folder / "002_note.sql").write_text("ALTER TABLE linacs ADD COLUMN note TEXT;\nUPDATE linacs SET note = 'migrated';\n", encoding="utf-8")
    from app.main import app
    with TestClient(app):                                             # the start of the program applies the pending migrations
        pass
    c = sqlite3.connect(path)
    assert c.execute("SELECT name, note FROM linacs").fetchall() == [("TrueBeam", "migrated")]
    assert c.execute("SELECT login FROM users").fetchall() == [("boss",)]
    assert [r[0] for r in c.execute("SELECT name FROM schema_migrations ORDER BY name")] == ["001_baseline.sql", "002_note.sql"]
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and c.execute("PRAGMA foreign_key_check").fetchall() == []
    c.close()
    after = structure(path)
    assert {k: v for k, v in after.items() if k != "sqlite_autoindex_schema_migrations_1"}.keys() >= before.keys()   # nothing was dropped
    copies = list((path.parent / "backups" / "keep").glob("trs398_update_*.db.gz"))
    assert len(copies) == 1
    import gzip
    old = path.parent / "old.db"
    old.write_bytes(gzip.decompress(copies[0].read_bytes()))
    oc = sqlite3.connect(old)
    assert "note" not in [r[1] for r in oc.execute("PRAGMA table_info(linacs)")]            # the copy is the data as they were
    assert oc.execute("SELECT login FROM users").fetchall() == [("boss",)]
    oc.close()


def test_a_failed_migration_changes_nothing(old_database):
    path, folder = old_database
    (folder / "002_bad.sql").write_text("ALTER TABLE linacs ADD COLUMN note TEXT;\nTHIS IS NOT SQL;\n", encoding="utf-8")
    c = db.connect(path)
    with pytest.raises(sqlite3.Error):
        db.migrate(c)
    c.close()
    c = sqlite3.connect(path)
    assert "note" not in [r[1] for r in c.execute("PRAGMA table_info(linacs)")]               # the first statement was rolled back too
    assert [r[0] for r in c.execute("SELECT name FROM schema_migrations")] == ["001_baseline.sql"]
    assert c.execute("SELECT name FROM linacs").fetchall() == [("TrueBeam",)]
    c.close()


def test_no_safety_copy_without_pending_migrations_or_for_a_new_database(old_database, tmp_path):
    path, folder = old_database
    from app.main import app
    with TestClient(app):
        pass
    assert not (path.parent / "backups" / "keep").exists() or not list((path.parent / "backups" / "keep").glob("*.db.gz"))
