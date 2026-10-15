"""The released program has no console: the server must start with sys.stdout/sys.stderr equal to None (a crash found at the first pilot)."""
import importlib
import sys


def test_the_server_can_be_configured_without_console_streams(monkeypatch, tmp_path):
    monkeypatch.setenv("TRS_DATA", str(tmp_path))
    monkeypatch.setenv("TRS_NO_SCHEDULER", "1")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    sys.modules.pop("tray", None)
    tray = importlib.import_module("tray")
    assert sys.stdout is not None and sys.stderr is not None          # replaced at the import
    server = tray.Server(8199, False)
    assert server.server.config.log_config is None
    sys.modules.pop("tray", None)


def test_the_server_does_not_pick_up_leftover_protocol_modules(monkeypatch, tmp_path):
    """A new version unpacked over an old folder leaves httptools/websockets there; the server must not use them (it failed silently once)."""
    monkeypatch.setenv("TRS_DATA", str(tmp_path))
    sys.modules.pop("tray", None)
    tray = importlib.import_module("tray")
    config = tray.Server(8198, False).server.config
    assert (config.http, config.ws, config.loop, config.lifespan) == ("h11", "none", "asyncio", "on")
    sys.modules.pop("tray", None)


def test_a_server_that_cannot_start_leaves_crash_log(monkeypatch, tmp_path):
    import socket
    monkeypatch.setenv("TRS_DATA", str(tmp_path))
    monkeypatch.setenv("TRS_NO_SCHEDULER", "1")
    sys.modules.pop("tray", None)
    tray = importlib.import_module("tray")
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        server = tray.Server(busy.getsockname()[1], False)           # the port is taken: the start-up fails
        server.start()
        server.thread.join(timeout=20)
    assert (tmp_path / "crash.log").exists()
    sys.modules.pop("tray", None)
