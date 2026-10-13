"""First run: with no users the browser asks for the administrator; the page is closed as soon as one exists."""
import re

from fastapi.testclient import TestClient

from tests.test_app import client, q, token  # noqa: F401  (fixture is discovered here)


def fresh_app(client):
    from tests import sqlcompat
    with sqlcompat.connect(client.owner_url, autocommit=True) as conn:
        conn.execute("INSERT INTO _maintenance(k) VALUES ('purge')")
        conn.execute("DELETE FROM users")                              # the bootstrap administrator of the fixture: back to a new database
    from app.main import app
    c = TestClient(app, follow_redirects=False)
    c.__enter__()
    return c


def test_empty_database_sends_everything_to_setup_and_creates_the_administrator(client, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD")                   # as on a real first run: no password in .env
    c = fresh_app(client)
    assert c.get("/measurements").headers["location"] == "/login"
    assert c.get("/login").headers["location"] == "/setup"
    page = c.get("/setup")
    assert page.status_code == 200 and "Первый запуск" in page.text
    tok = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)

    def send(**over):
        data = dict(login="boss", full_name="Иванов И. И.", password="a-long-password-1", password2="a-long-password-1", csrf=tok)
        data.update(over)
        return c.post("/setup", data=data)

    assert send(login="x y").status_code == 422
    assert send(password="short", password2="short").status_code == 422
    assert send(password2="another-password-9").status_code == 422
    assert send(full_name="").status_code == 422
    assert q(client, "SELECT count(*) FROM users")[0][0] == 0                  # nothing created by the failed attempts
    ok = send()
    assert ok.status_code == 303 and ok.headers["location"] == "/login?created=1"
    assert q(client, "SELECT login, full_name, role, is_active FROM users") == [("boss", "Иванов И. И.", "admin", True)]
    assert q(client, "SELECT count(*) FROM audit_log WHERE action = 'setup_admin'")[0][0] == 1
    assert "Администратор создан" in c.get("/login?created=1").text


def test_setup_is_closed_once_a_user_exists(client):
    c = TestClient(__import__("app.main", fromlist=["app"]).app, follow_redirects=False)
    c.__enter__()
    assert c.get("/setup").headers["location"] == "/login"
    tok = token(c)
    r = c.post("/setup", data=dict(login="intruder", full_name="X", password="a-long-password-1", password2="a-long-password-1", csrf=tok))
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert q(client, "SELECT count(*) FROM users WHERE login = 'intruder'")[0][0] == 0
