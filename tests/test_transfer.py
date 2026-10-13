"""Moving a database to another copy of the program: make_transfer.py makes the file, restore.py (and load-test-db.bat) loads it."""
import gzip
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_transfer  # noqa: E402
import restore  # noqa: E402
from app import db  # noqa: E402


def database(path: Path, linacs=("TrueBeam",)) -> Path:
    c = db.connect(path)
    db.migrate(c)
    for name in linacs:
        c.execute("INSERT INTO linacs(name) VALUES (%s)", (name,))
    c.commit()
    c.close()
    return path


def names(path) -> list[str]:
    c = sqlite3.connect(path)
    try:
        return [r[0] for r in c.execute("SELECT name FROM linacs ORDER BY id")]
    finally:
        c.close()


@pytest.fixture()
def target(tmp_path, monkeypatch):
    data = tmp_path / "other" / "data"
    data.mkdir(parents=True)
    monkeypatch.setenv("TRS_DATA", str(data))
    monkeypatch.setenv("TRS_DB", str(data / "trs398.db"))
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    database(data / "trs398.db", linacs=("Old",))
    return data


def test_make_transfer_writes_a_checked_backup_file(tmp_path):
    (tmp_path / "src").mkdir()
    source = database(tmp_path / "src" / "trs398.db", linacs=("TrueBeam", "Versa HD"))
    out = tmp_path / "out"
    path = make_transfer.make(source, out, datetime(2026, 10, 13, 12, 0, 0))
    assert path == out / "trs398_2026-10-13_120000.db.gz"
    plain = tmp_path / "check.db"
    plain.write_bytes(gzip.decompress(path.read_bytes()))
    assert names(plain) == ["TrueBeam", "Versa HD"]
    assert make_transfer.find_source(str(source)) == source and make_transfer.find_source(str(source.parent)) == source


def test_restore_with_yes_loads_a_backup_file_without_asking(target, tmp_path, monkeypatch):
    src = database(tmp_path / "src.db", linacs=("TrueBeam", "Versa HD"))
    gz = make_transfer.make(src, tmp_path / "transfer")
    monkeypatch.setattr(sys, "argv", ["restore", str(gz), "--yes"])
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("must not ask with --yes"))
    restore.main()
    assert names(target / "trs398.db") == ["TrueBeam", "Versa HD"]
    kept = list((target / "backups" / "keep").glob("trs398_*.db.gz"))
    assert len(kept) == 1                                                               # the replaced database is kept
    assert (target / "restored.json").exists()


def test_restore_takes_a_plain_database_file_and_a_folder(target, tmp_path, monkeypatch):
    plain = database(tmp_path / "plain.db", linacs=("Plain",))
    monkeypatch.setattr(sys, "argv", ["restore", str(plain), "--yes"])
    restore.main()
    assert names(target / "trs398.db") == ["Plain"]
    folder = tmp_path / "drop"
    (folder / "transfer").mkdir(parents=True)
    make_transfer.make(database(tmp_path / "x.db", linacs=("FromFolder",)), folder / "transfer")
    monkeypatch.setattr(sys, "argv", ["restore", str(folder), "--yes"])                  # the newest file of the folder or of its `transfer`
    restore.main()
    assert names(target / "trs398.db") == ["FromFolder"]


def test_restore_without_yes_still_asks_and_cancels_on_anything_else(target, tmp_path, monkeypatch):
    gz = make_transfer.make(database(tmp_path / "s.db", linacs=("New",)), tmp_path / "t")
    monkeypatch.setattr(sys, "argv", ["restore", str(gz)])
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    with pytest.raises(SystemExit):
        restore.main()
    assert names(target / "trs398.db") == ["Old"]


def test_a_damaged_file_changes_nothing(target, tmp_path, monkeypatch):
    bad = tmp_path / "bad.db.gz"
    bad.write_bytes(gzip.compress(b"this is not a database"))
    monkeypatch.setattr(sys, "argv", ["restore", str(bad), "--yes"])
    with pytest.raises(Exception):
        restore.main()
    assert names(target / "trs398.db") == ["Old"]


def test_the_bat_file_is_in_the_repository_and_in_the_portable_build():
    text = (ROOT / "load-test-db.bat").read_bytes()
    assert b"restore" in text and b"--yes" in text and b"\r\n" in text                  # a Windows batch file with CRLF line ends
    assert "load-test-db.bat" in (ROOT / "tools" / "build_windows.py").read_text(encoding="utf-8")
