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
