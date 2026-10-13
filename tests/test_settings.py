"""The page "Settings" of the administrator, the settings file, and the tray controller that applies the port and the network access."""
import datetime as dt
import importlib
import json
import sys

import pytest

from app import backups, i18n, settings
from tests.test_app import client, post, q, world  # noqa: F401  (fixtures are discovered here)


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("TRS_DATA", str(tmp_path))
    monkeypatch.setenv("TRS_DB", str(tmp_path / "trs398.db"))
    for name in ("TRS_LANG", "BACKUP_HOUR", "BACKUP_KEEP_DAYS", "BACKUP_COPY_DIR", "BACKUP_DIR"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_validate_accepts_good_values_and_explains_bad_ones():
    ok, errors = settings.validate({"port": "8100", "lan": "1", "language": "en", "backup_hour": "3", "backup_keep_days": "60"})
    assert not errors and ok == {"port": 8100, "lan": True, "language": "en", "backup_hour": 3, "backup_keep_days": 60}
    ok, errors = settings.validate({"port": "80", "language": "de", "backup_hour": "24", "backup_keep_days": "x"})
    assert len(errors) == 4 and ok["lan"] is False and ok["language"] == "ru"
    assert any("Порт" in e and "1024" in e for e in errors) and any("Срок хранения" in e and "целое" in e for e in errors)


def test_the_file_is_read_with_defaults_and_survives_damage(data):
    assert settings.load() == settings.DEFAULTS
    settings.save({**settings.DEFAULTS, "port": 8100})
    assert settings.load()["port"] == 8100 and settings.load()["backup_hour"] == 2
    (data / "settings.json").write_text("{ broken", encoding="utf-8")
    assert settings.load() == settings.DEFAULTS


def test_the_settings_reach_the_language_and_the_backups(data, monkeypatch):
    settings.save({**settings.DEFAULTS, "language": "en", "backup_hour": 5, "backup_keep_days": 7})
    assert i18n.default_lang() == "en" and backups.keep_days() == 7
    assert backups.due(dt.datetime(2026, 10, 13, 4, 59)) is False and backups.due(dt.datetime(2026, 10, 13, 5, 0)) is True
    monkeypatch.setenv("TRS_LANG", "ru")                                    # an environment variable is stronger
    monkeypatch.setenv("BACKUP_KEEP_DAYS", "90")
    assert i18n.default_lang() == "ru" and backups.keep_days() == 90


def test_the_page_is_for_the_administrator_and_saves_valid_values(world, client):
    page = "/admin/settings"
    assert world["phys"].get(page).status_code == 403 and world["view"].get(page).status_code == 403
    html = world["adm"].get(page).text
    assert "Настройки" in html and 'name="port"' in html and "Адрес для коллег" in html
    form = {"port": "8100", "lan": "1", "language": "en", "backup_hour": "4", "backup_keep_days": "45"}
    r = post(world["adm"], page, form, page=page)
    assert r.status_code == 303 and r.headers["location"] == "/admin/settings?saved=1"
    s = settings.load()
    assert (s["port"], s["lan"], s["language"], s["backup_hour"], s["backup_keep_days"]) == (8100, True, "en", 4, 45)
    assert "Saved" in world["adm"].get(r.headers["location"]).text          # the default language is English now
    details = q(client, "SELECT details FROM audit_log WHERE action='settings_changed' ORDER BY id DESC LIMIT 1")[0][0]
    assert (details if isinstance(details, dict) else json.loads(details))["port"] == 8100
    assert post(world["phys"], page, form, page="/measurements").status_code == 403
    settings.save(dict(settings.DEFAULTS))                                                                         # back to the defaults


def test_bad_values_are_refused_and_nothing_is_saved(world, client):
    settings.save(dict(settings.DEFAULTS))
    before = settings.load()
    r = post(world["adm"], "/admin/settings", {"port": "22", "language": "ru", "backup_hour": "2", "backup_keep_days": "30"}, page="/admin/settings")
    assert r.status_code == 422 and "Порт" in r.text and "1024" in r.text
    assert settings.load() == before


def test_the_folder_of_the_second_copy_is_not_touched_by_the_page(world, client, tmp_path):
    settings.save({**settings.load(), "backup_copy_dir": str(tmp_path / "second")})
    post(world["adm"], "/admin/settings", {"port": "8000", "language": "ru", "backup_hour": "2", "backup_keep_days": "30"}, page="/admin/settings")
    assert settings.load()["backup_copy_dir"] == str(tmp_path / "second")
    settings.save({**settings.load(), "backup_copy_dir": ""})


def test_an_environment_variable_is_announced_on_the_page(world, monkeypatch):
    monkeypatch.setenv("BACKUP_HOUR", "6")
    assert "BACKUP_HOUR" in world["adm"].get("/admin/settings").text


# --------------------------------------------------------------------------- the tray applies the file
class FakeServer:
    started = []

    def __init__(self, port, lan):
        self.port, self.lan, self.stopped = port, lan, False

    def start(self):
        FakeServer.started.append((self.port, self.lan))

    def stop(self):
        self.stopped = True


@pytest.fixture()
def tray(data, monkeypatch):
    monkeypatch.setattr(sys, "stdout", sys.stdout or open("nul", "w"))
    sys.modules.pop("tray", None)
    module = importlib.import_module("tray")
    monkeypatch.setattr(module, "Server", FakeServer)
    FakeServer.started.clear()
    yield module
    sys.modules.pop("tray", None)


def test_the_controller_restarts_the_server_when_the_port_or_the_access_changes(tray, monkeypatch):
    monkeypatch.setattr(tray, "port_busy", lambda p: False)
    ctl = tray.Controller({"port": 8000, "lan": False})
    first = ctl.server
    assert ctl.sync({"port": 8000, "lan": False}) == "same" and not first.stopped
    assert ctl.sync({"port": 8000, "lan": True}) == "restarted" and first.stopped and FakeServer.started[-1] == (8000, True)
    assert ctl.sync({"port": 8100, "lan": True}) == "restarted" and ctl.url == "http://localhost:8100"
    assert FakeServer.started == [(8000, False), (8000, True), (8100, True)]


def test_a_port_used_by_another_program_is_refused_and_the_old_one_is_put_back(tray, monkeypatch):
    ctl = tray.Controller({"port": 8000, "lan": False})
    monkeypatch.setattr(tray, "port_busy", lambda p: p == 8200)
    settings.save({**settings.DEFAULTS, "port": 8200})
    assert ctl.sync({"port": 8200, "lan": False}) == "busy"
    assert ctl.port == 8000 and settings.load()["port"] == 8000 and FakeServer.started == [(8000, False)]
