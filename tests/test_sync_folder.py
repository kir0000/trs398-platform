from pathlib import Path

from app import health


def test_cloud_folder_names_are_recognised(tmp_path):
    for name, service in [("Yandex.Disk", "Яндекс.Диск"), ("OneDrive - Clinic", "OneDrive"), ("Dropbox", "Dropbox"), ("Google Drive", "Google Drive")]:
        folder = tmp_path / name / "TRS398" / "data"
        folder.mkdir(parents=True)
        assert health.sync_service(folder) == service


def test_plain_folder_is_not_flagged(tmp_path):
    folder = tmp_path / "TRS398" / "data"
    folder.mkdir(parents=True)
    assert health.sync_service(folder) == ""


def test_marker_file_and_onedrive_variable(tmp_path, monkeypatch):
    root = tmp_path / "share"
    (root / "data").mkdir(parents=True)
    (root / ".dropbox").write_text("")
    assert health.sync_service(root / "data") == "Dropbox"
    other = tmp_path / "work" / "data"
    other.mkdir(parents=True)
    monkeypatch.setenv("OneDrive", str(tmp_path / "work"))
    assert health.sync_service(other) == "OneDrive"


def test_check_records_the_service(tmp_path):
    import sqlite3
    folder = tmp_path / "Dropbox"
    folder.mkdir()
    path = folder / "x.db"
    sqlite3.connect(path).close()
    assert health.check(path)["sync"] == "Dropbox"
    folder2 = tmp_path / "plain"
    folder2.mkdir()
    path2 = folder2 / "x.db"
    sqlite3.connect(path2).close()
    assert health.check(path2)["sync"] == ""
