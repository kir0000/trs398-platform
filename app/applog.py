"""The log of the program: data/app.log (rotating, 3 files of 1 MB). Start, errors of requests and background jobs end up here,
so that a physicist can send the file when something goes wrong. Measurement data and passwords are never written to it."""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import db

NAME = "trs398"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def log_path() -> Path:
    return db.data_dir() / "app.log"


def setup(version: str = "") -> logging.Handler | None:
    """Attach the file handler to the root logger (everything at WARNING and above, the program's own messages from INFO)."""
    try:
        handler = RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except OSError:                                          # a read-only folder must not stop the program
        return None
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(min(root.level or logging.WARNING, logging.WARNING))
    own = logging.getLogger(NAME)
    own.setLevel(logging.INFO)

    def hook(exc_type, exc, tb):
        own.error("unhandled exception", exc_info=(exc_type, exc, tb))

    def thread_hook(args):
        own.error("unhandled exception in thread %s", args.thread.name if args.thread else "?", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = hook
    threading.excepthook = thread_hook
    own.info("start, version %s, data %s", version or "?", db.data_dir())
    return handler


def teardown(handler: logging.Handler | None) -> None:
    if handler is not None:
        logging.getLogger(NAME).info("stop")
        logging.getLogger().removeHandler(handler)
        handler.close()


def tail(lines: int = 60) -> str:
    """The last lines of the log (for the 'About' page)."""
    try:
        return "".join(log_path().read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)[-lines:])
    except OSError:
        return ""
