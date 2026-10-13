"""The 'About' page and the check for a newer version (the network is never touched by the tests)."""
from app import updates
from tests.test_app import client, post, world  # noqa: F401  (fixtures are discovered here)


def test_version_order():
    k = updates.version_key
    assert k("2.0.0-rc2") < k("2.0.0") < k("2.0.1") < k("v2.1.0") and k("2.0.0-rc1") < k("2.0.0-rc2")
    assert k("2.0.0+dev") == k("2.0.0")


def test_check_reports_newer_equal_and_errors():
    fake = lambda tag: (lambda: {"tag_name": tag, "html_url": "https://example.test/r"})          # noqa: E731
    assert updates.check("2.0.0-rc2", fake("v2.0.0"))["newer"] is True
    assert updates.check("2.0.0", fake("v2.0.0"))["newer"] is False
    def boom():
        raise OSError("no network")
    r = updates.check("2.0.0", boom)
    assert r["ok"] is False and "no network" in r["error"]


def test_about_page_is_open_to_every_role_and_does_not_call_the_network(world, monkeypatch):
    called = []
    monkeypatch.setattr(updates, "check", lambda current: called.append(current) or {"ok": True, "latest": "v9.9.9", "url": "https://example.test/r", "newer": True})
    for who in ("phys", "adm"):
        r = world[who].get("/about")
        assert r.status_code == 200 and "О программе" in r.text and "Проверить обновления" in r.text
    assert not called                                           # opening the page sends nothing
    r = post(world["phys"], "/about/check", page="/about")
    assert r.status_code == 200 and "v9.9.9" in r.text and "Вышла новая версия" in r.text and len(called) == 1
