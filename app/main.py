"""TRS-398 Rev.1 absolute dose platform: FastAPI + Jinja2 + HTMX."""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app import applog, backups, netaccess, services
from app.db import audit, connect, data_dir, migrate, request_ip, session_secret, system_event
from app.db import has_data as db_has_data
from app.db import pending as db_pending
from app.routes import admin, equipment, measurements, pages, trends, uncertainty
from app.security import MIN_PASSWORD_LENGTH, hash_password
from app.web import BASE, NotAuthenticated, app_version, has_users, render

# the names that tests and tools import from app.main (they live in the modules of their parts)
from app.common import add_months, beam_label, calibration_state  # noqa: E402,F401
from app.routes.admin import PURGE_CONFIRMATIONS  # noqa: E402,F401
from app.routes.equipment import beam_readiness, eq_back  # noqa: E402,F401
from app.routes.measurements import form_values  # noqa: E402,F401
from app.web import signed_over  # noqa: E402,F401


def note_restore():
    """tools/restore.py leaves a marker; the program writes the record into the restored database at its start."""
    marker = data_dir() / "restored.json"
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    system_event("restore", "system", None, info)
    marker.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(_app):
    log_handler = applog.setup(app_version())
    conn = connect()
    try:
        todo = db_pending(conn)
        if todo and db_has_data(conn):                         # an update changes the structure: keep a copy of the data as it was
            keep = backups.backup_dir() / "keep"
            keep.mkdir(parents=True, exist_ok=True)
            try:
                kept = backups.make(folder=keep, name_prefix="trs398_update")
                logging.getLogger("trs398").info("before %s a safety copy was made: %s", ", ".join(todo), kept.name)
            except Exception:                                  # noqa: BLE001
                logging.getLogger("trs398").exception("the safety copy before the update failed")
                raise
        migrate(conn)
        if todo:
            system_event("migration_applied", "system", None, {"names": todo})
        services.seed_chambers(conn)
        login, password = os.environ.get("BOOTSTRAP_ADMIN_LOGIN"), os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
        if login and password and not has_users(conn):
            if len(password) < MIN_PASSWORD_LENGTH:
                raise RuntimeError(f"BOOTSTRAP_ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters")
            conn.execute("INSERT INTO users(login, full_name, role, password_hash) VALUES (%s, %s, 'admin', %s)",
                         (login, "Администратор", hash_password(password)))
            audit(conn, None, "bootstrap_admin", "users", login)
        conn.commit()
    finally:
        conn.close()
    system_event("app_start", "system", None, {"version": app_version()})
    note_restore()
    if os.environ.get("TRS_NO_SCHEDULER") != "1":
        backups.start_scheduler()
    yield
    applog.teardown(log_handler)


app = FastAPI(title="TRS-398 Rev.1", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")      # htmx and Plotly are served locally: no internet needed
app.add_middleware(SessionMiddleware, secret_key=session_secret(), same_site="lax", max_age=72 * 3600,
                   https_only=os.environ.get("HTTPS_ONLY") == "1")


DENIED_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    "<title>403</title><style>body{font:16px system-ui,sans-serif;max-width:560px;margin:12vh auto;padding:0 16px;color:#222}</style></head><body>"
    "<h1>403</h1><p>Доступ с этого адреса не разрешён. Обратитесь к администратору программы.</p>"
    "<p>Access from this address is not allowed. Ask the administrator of the program.</p></body></html>")


@app.middleware("http")
async def guard_the_address(request: Request, call_next):
    """Only the allowed addresses (settings: "Allowed addresses") may use the program; the computer itself always may."""
    host = request.client.host if request.client else None
    if not netaccess.is_allowed(host):
        if netaccess.should_log_denial(host):
            token = request_ip.set(host)
            try:
                system_event("access_denied", "system", None, {"path": request.url.path[:80]})
            finally:
                request_ip.reset(token)
        return HTMLResponse(DENIED_PAGE, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def remember_the_address(request: Request, call_next):
    """The address the request came from goes into every audit record of this request (app.db.audit)."""
    token = request_ip.set(request.client.host if request.client else None)
    try:
        return await call_next(request)
    finally:
        request_ip.reset(token)


@app.exception_handler(NotAuthenticated)
async def _redirect_to_login(_request, _exc):
    return RedirectResponse("/login" + (f"?ended={_exc.reason}" if getattr(_exc, "reason", "") else ""), status_code=303)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path == "/healthz" or request.headers.get("hx-request"):
        return Response(str(exc.detail), status_code=exc.status_code, media_type="text/plain; charset=utf-8")
    user = None
    uid = request.session.get("uid") if "session" in request.scope else None
    if uid:
        conn = connect()
        try:
            user = conn.execute("SELECT id, login, full_name, role FROM users WHERE id = %s AND is_active",
                                (uid,)).fetchone()
        finally:
            conn.close()
    return render(request, "error.html", user, status_code=exc.status_code, code=exc.status_code, message=exc.detail)


app.include_router(pages.router)
app.include_router(measurements.router)
app.include_router(trends.router)
app.include_router(uncertainty.router)
app.include_router(equipment.router)
app.include_router(admin.router)
