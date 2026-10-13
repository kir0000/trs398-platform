"""The log file of the program: it exists, receives errors of background jobs and of unhandled exceptions, and does not stop the program."""
import logging
import sys
import threading

from app import applog, backups


def test_the_log_gets_start_backup_errors_and_unhandled_exceptions(monkeypatch, tmp_path):
    monkeypatch.setenv("TRS_DATA", str(tmp_path))
    old_hooks = sys.excepthook, threading.excepthook
    handler = applog.setup("9.9.9")
    try:
        assert handler is not None and applog.log_path() == tmp_path / "app.log"

        def boom(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(backups, "make", boom)
        assert backups.request_now() is False
        try:
            raise RuntimeError("something broke")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        logging.getLogger("uvicorn.error").error("Exception in ASGI application")
    finally:
        applog.teardown(handler)
        sys.excepthook, threading.excepthook = old_hooks
    text = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "start, version 9.9.9" in text and "the backup failed" in text and "disk full" in text
    assert "unhandled exception" in text and "RuntimeError: something broke" in text and "Exception in ASGI application" in text
    assert "stop" in text
    assert applog.tail(3).count("\n") <= 3


def test_an_unwritable_folder_does_not_stop_the_program(monkeypatch, tmp_path):
    monkeypatch.setenv("TRS_DATA", str(tmp_path))
    (tmp_path / "app.log").mkdir()                       # a directory in place of the file: opening it fails
    assert applog.setup("1.0") is None
    applog.teardown(None)
