"""Network security: the list of allowed addresses and the lifetime of a session (the absolute one and the idle one)."""
import ipaddress

import pytest
from fastapi.testclient import TestClient

from app import netaccess, settings, web
from tests.test_app import ADMIN_PW, client, post, q, world  # noqa: F401  (fixtures are discovered here)


@pytest.fixture(autouse=True)
def clean_settings(client, monkeypatch):
    monkeypatch.delenv("TRS_ALLOWED_NETWORKS", raising=False)
    settings.save(dict(settings.DEFAULTS))
    netaccess._denied.clear()
    yield
    settings.save(dict(settings.DEFAULTS))


def from_address(ip):
    from app.main import app
    return TestClient(app, client=(ip, 51000), follow_redirects=False)


# --------------------------------------------------------------------------- the list of addresses
def test_parse_accepts_addresses_and_networks_and_reports_the_rest():
    nets, bad = netaccess.parse("192.168.1.0/24, 10.0.0.15;fe80::/10\n  300.1.1.1  host.local")
    assert [str(n) for n in nets] == ["192.168.1.0/24", "10.0.0.15/32", "fe80::/10"] and bad == ["300.1.1.1", "host.local"]
    assert netaccess.parse("") == ([], []) and netaccess.parse("  ,; ") == ([], [])


def test_the_rules_of_the_list():
    nets = netaccess.parse("192.168.1.0/24, 10.0.0.15")[0]
    allowed = lambda host: netaccess.is_allowed(host, nets)                          # noqa: E731
    assert allowed("192.168.1.77") and allowed("10.0.0.15") and allowed("::ffff:192.168.1.5")        # an IPv4 address inside IPv6
    assert not allowed("192.168.2.1") and not allowed("10.0.0.16") and not allowed("8.8.8.8")
    assert allowed("127.0.0.1") and allowed("::1")                                   # the computer itself always may
    assert not allowed("testclient") and not allowed(None) and not allowed("")       # not an address: not trusted when a list is set
    assert netaccess.is_allowed("8.8.8.8", []) and netaccess.is_allowed("testclient", [])        # no list: everybody
    assert netaccess.client_address("fe80::1%eth0") == ipaddress.ip_address("fe80::1")


def test_a_refused_address_gets_403_and_one_record_an_hour(world, client):
    settings.save({**settings.DEFAULTS, "allowed_networks": "192.168.1.0/24"})
    outsider = from_address("10.9.8.7")
    r = outsider.get("/login")
    assert r.status_code == 403 and "Доступ с этого адреса не разрешён" in r.text and "not allowed" in r.text
    assert outsider.get("/measurements").status_code == 403 and outsider.post("/login", data={"login": "x", "password": "y"}).status_code == 403
    rows = q(client, "SELECT ip, details FROM audit_log WHERE action='access_denied'")
    assert len(rows) == 1 and rows[0][0] == "10.9.8.7"                               # the attempts of one address in an hour: one record
    assert from_address("192.168.1.9").get("/login").status_code == 200                # an address of the list
    assert from_address("127.0.0.1").get("/login").status_code == 200                  # the computer itself
    assert from_address("10.9.8.8").get("/login").status_code == 403
    assert q(client, "SELECT count(*) FROM audit_log WHERE action='access_denied'")[0][0] == 2   # another address: its own record
    assert netaccess.should_log_denial("10.9.8.7", now=10 ** 10) is True               # an hour later it is logged again


def test_the_file_and_the_environment_are_followed_without_a_restart(world, client, monkeypatch):
    outsider = from_address("10.9.8.7")
    assert outsider.get("/login").status_code == 200                                   # no list: open
    settings.save({**settings.DEFAULTS, "allowed_networks": "10.9.8.0/24"})
    assert outsider.get("/login").status_code == 200
    settings.save({**settings.DEFAULTS, "allowed_networks": "172.16.0.0/12"})
    assert outsider.get("/login").status_code == 403                                   # the file changed
    monkeypatch.setenv("TRS_ALLOWED_NETWORKS", "10.9.8.7")
    assert outsider.get("/login").status_code == 200                                   # the environment is stronger
    monkeypatch.setenv("TRS_ALLOWED_NETWORKS", "")
    assert outsider.get("/login").status_code == 200                                   # an empty value of the environment: nobody is limited


# --------------------------------------------------------------------------- the page of settings
def test_settings_validation_of_the_new_fields():
    ok, errors = settings.validate({"port": "8000", "language": "ru", "backup_hour": "2", "backup_keep_days": "30",
                                    "session_hours": "12", "session_idle_minutes": "45", "allowed_networks": "192.168.1.0/24; 10.0.0.15"})
    assert not errors and ok["session_hours"] == 12 and ok["session_idle_minutes"] == 45 and ok["allowed_networks"] == "192.168.1.0/24, 10.0.0.15"
    _, errors = settings.validate({"port": "8000", "language": "ru", "backup_hour": "2", "backup_keep_days": "30",
                                   "session_hours": "100", "session_idle_minutes": "x", "allowed_networks": "nonsense"})
    assert len(errors) == 3
    ok, errors = settings.validate({"port": "8000", "language": "ru", "backup_hour": "2", "backup_keep_days": "30"})        # an old form: nothing new
    assert not errors and "session_hours" not in ok and "allowed_networks" not in ok


def test_the_administrator_cannot_lock_himself_out_and_the_page_saves_the_rest(world, client):
    from tests.test_app import token
    adm = from_address("192.168.5.5")
    assert adm.post("/login", data={"login": "admin", "password": ADMIN_PW, "csrf": token(adm)}).status_code == 303
    base = {"port": "8000", "language": "ru", "backup_hour": "2", "backup_keep_days": "30", "session_hours": "8", "session_idle_minutes": "0"}
    r = post(adm, "/admin/settings", dict(base, allowed_networks="10.0.0.0/8"), page="/admin/settings")
    assert r.status_code == 422 and "Ваш адрес 192.168.5.5 не входит" in r.text and settings.load()["allowed_networks"] == ""
    r = post(adm, "/admin/settings", dict(base, allowed_networks="192.168.5.0/24, 10.0.0.15", session_hours="12", session_idle_minutes="45"), page="/admin/settings")
    assert r.status_code == 303
    s = settings.load()
    assert s["allowed_networks"] == "192.168.5.0/24, 10.0.0.15" and s["session_hours"] == 12 and s["session_idle_minutes"] == 45
    page = adm.get("/admin/settings").text
    assert "192.168.5.0/24, 10.0.0.15" in page and 'name="session_idle_minutes"' in page and "Безопасность сети" in page
    r = post(adm, "/admin/settings", dict(base, allowed_networks="not an address"), page="/admin/settings")
    assert r.status_code == 422 and "не адрес или сеть" in r.text
    post(adm, "/admin/settings", dict(base, allowed_networks=""), page="/admin/settings")                       # back to open
    assert settings.load()["allowed_networks"] == ""
    assert "TRS_ALLOWED_NETWORKS" not in adm.get("/admin/settings").text


# --------------------------------------------------------------------------- the lifetime of a session
def test_the_lifetime_rules_in_numbers():
    check = web.check_session_lifetime
    s = {}
    assert check(s, 1000.0, 8, 30) == "" and s == {"login_at": 1000.0, "last": 1000.0}          # an old cookie without times starts now
    s = {"login_at": 0.0, "last": 0.0}
    assert check(s, 29 * 60, 8, 30) == "" and s["last"] == 29 * 60                            # active: the time of the last activity moves
    assert check(s, 29 * 60 + 20, 8, 30) == "" and s["last"] == 29 * 60                      # ... but is written no more often than every 30 s
    assert check(s, 29 * 60 + 31 * 60, 8, 30) == "idle"
    assert check({"login_at": 0.0, "last": 7 * 3600 + 3000.0}, 8 * 3600 + 1, 8, 0) == "age"   # the absolute limit, also with the idle one off
    assert check({"login_at": 0.0, "last": 10.0}, 20 * 3600, 24, 0) == ""                      # the idle limit 0: never idle


@pytest.fixture()
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(web, "clock", lambda: now[0])
    return now


def test_idle_session_ends_with_a_message_and_activity_keeps_it_alive(world, client, clock):
    from tests.test_app import PHYS_PW, token
    settings.save({**settings.DEFAULTS, "session_idle_minutes": 30})
    s = from_address("127.0.0.1")
    assert s.post("/login", data={"login": "phys", "password": PHYS_PW, "csrf": token(s)}).status_code == 303      # signed in at the fake time
    for _ in range(4):                                                                         # active every 25 minutes: alive after 100 minutes
        clock[0] += 25 * 60
        assert s.get("/measurements").status_code == 200
    clock[0] += 31 * 60
    r = s.get("/measurements")
    assert r.status_code == 303 and r.headers["location"] == "/login?ended=idle"
    assert "слишком долго не было действий" in s.get("/login?ended=idle").text
    assert s.get("/measurements").headers["location"] == "/login"                              # the session is cleared (no reason this time)


def test_the_absolute_limit_ends_even_an_active_session(world, client, clock):
    settings.save({**settings.DEFAULTS, "session_hours": 1})
    s = from_address("127.0.0.1")
    from tests.test_app import PHYS_PW, token
    assert s.post("/login", data={"login": "phys", "password": PHYS_PW, "csrf": token(s)}).status_code == 303
    for _ in range(5):                                                                         # active every 10 minutes
        clock[0] += 10 * 60
        assert s.get("/measurements").status_code == 200
    clock[0] += 11 * 60                                                                        # 61 minutes since the sign-in
    r = s.get("/measurements")
    assert r.status_code == 303 and r.headers["location"] == "/login?ended=age"
    assert "истёк его срок" in s.get("/login?ended=age").text
    assert "слишком" not in s.get("/login?ended=nonsense").text                               # an unknown reason shows nothing


def test_the_messages_are_translated(world, client):
    s = from_address("127.0.0.1")
    s.get("/lang/en")
    assert "no activity for too long" in s.get("/login?ended=idle").text and "its time is over" in s.get("/login?ended=age").text
