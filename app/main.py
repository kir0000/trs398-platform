"""TRS-398 Rev.1 absolute dose platform: FastAPI + Jinja2 + HTMX."""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import backups, fields, i18n, protocol, services
from app.notation import sym, sym_plain
from app.chart import control_chart
from core import uncertainty_distributions as udist
from core import uncertainty_literature as ulit
from app import applog, auditlog, dbops, trend_export, settings as app_settings, updates
from app.pdf import PdfUnavailable, html_to_pdf
from app.db import audit, connect, data_dir, db_path, get_db, migrate, request_ip, session_secret, system_event
from app.db import has_data as db_has_data, pending as db_pending
from app.security import (MIN_PASSWORD_LENGTH, ROLE_LABELS, ROLES, LoginThrottle, can_create, can_review,
                          hash_password, verify_password)
from core import electron as el_core
from core import compare, spc, uncertainty

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
def signed(x, digits: int = 2):
    """A deviation with an arrow instead of the sign: red ▲ above nominal, orange ▼ below."""
    from markupsafe import Markup
    if x is None:
        return "—"
    r = round(x, digits)
    if r == 0:
        return f"{abs(x):.{digits}f}"
    return Markup(f'<span class="{"dev-up" if r > 0 else "dev-down"}">{"▲" if r > 0 else "▼"}</span> {abs(x):.{digits}f}')


def signed_over(x, digits: int = 2, limit: float | None = None):
    """A signed value (+0.09 / −0.12); an arrow (red ▲, orange ▼) is added only where |x| exceeds the limit."""
    from markupsafe import Markup
    if x is None:
        return "—"
    r = round(x, digits)
    text = f"{abs(x):.{digits}f}" if r == 0 else f"{'+' if r > 0 else chr(0x2212)}{abs(x):.{digits}f}"
    if limit is not None and abs(x) > limit:
        return Markup(f'<span class="{"dev-up" if x > 0 else "dev-down"}">{"▲" if x > 0 else "▼"}</span> {text}')
    return text


templates.env.filters.update(sym=sym, sym_plain=sym_plain, signed=signed, signed_over=signed_over)
from markupsafe import Markup as _Markup
templates.env.globals.update(fa=lambda name: _Markup(fields.attrs(name)), fdatalists=lambda: _Markup(fields.datalists()))
throttle = LoginThrottle()
PURGE_CONFIRMATION = "УДАЛИТЬ"
PURGE_CONFIRMATIONS = ("УДАЛИТЬ", "DELETE")      # the word the page shows depends on the language; either is accepted
STATUS_LABELS = {"draft": "черновик", "submitted": "на проверке", "approved": "утверждено",
                 "returned": "возвращено", "superseded": "заменено", "voided": "аннулировано"}
PURGE_SCOPES = {"measurements": "Измерения и результаты", "legacy": "Исторические журналы (импорт)",
                "all": "Всё: измерения, результаты и исторические журналы"}


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
app.add_middleware(SessionMiddleware, secret_key=session_secret(), same_site="lax", max_age=8 * 3600,
                   https_only=os.environ.get("HTTPS_ONLY") == "1")


@app.middleware("http")
async def remember_the_address(request: Request, call_next):
    """The address the request came from goes into every audit record of this request (app.db.audit)."""
    token = request_ip.set(request.client.host if request.client else None)
    try:
        return await call_next(request)
    finally:
        request_ip.reset(token)


class NotAuthenticated(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def _redirect_to_login(_request, _exc):
    return RedirectResponse("/login", status_code=303)



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


def current_user(request: Request, conn=Depends(get_db)):
    uid = request.session.get("uid")
    if not uid:
        raise NotAuthenticated()
    u = conn.execute("SELECT id, login, full_name, role, is_active, password_hash FROM users WHERE id = %s",
                     (uid,)).fetchone()
    if not u or not u["is_active"]:
        request.session.clear()
        raise NotAuthenticated()
    return u


def require(*roles):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "Недостаточно прав для этого действия")
        return user
    return dep


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(24)
    return request.session["csrf"]


def check_csrf(request: Request, form) -> None:
    sent = form.get("csrf") or request.headers.get("x-csrf") or ""
    if not hmac.compare_digest(str(sent), request.session.get("csrf", "\0")):
        raise HTTPException(403, "Сессия устарела. Обновите страницу и повторите действие")


def current_lang(request: Request) -> str:
    """?lang= of the request (print/PDF links), then the session, the cookie, TRS_LANG from .env, Russian."""
    for value in (request.query_params.get("lang"), request.session.get("lang"), request.cookies.get("lang")):
        if value in i18n.LANGS:
            return value
    return i18n.default_lang()


def render(request: Request, name: str, user=None, status_code=200, **ctx):
    lang = current_lang(request)
    ctx.update(user=user, csrf=csrf_token(request), role_labels=ROLE_LABELS, status_labels=STATUS_LABELS,
               can_create=bool(user) and can_create(user["role"]), can_review=bool(user) and can_review(user["role"]),
               lang=lang, other_lang="en" if lang == "ru" else "ru", app_version=app_version())
    response = templates.TemplateResponse(request, name, ctx, status_code=status_code)
    return HTMLResponse(i18n.translate_html(response.body.decode("utf-8"), lang), status_code=status_code)


@app.get("/lang/{code}")
def set_language(request: Request, code: str, next: str = "/"):
    """Switch the interface language (remembered in the session and in a cookie for a year)."""
    if code not in i18n.LANGS:
        raise HTTPException(404, "Неизвестный язык")
    request.session["lang"] = code
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie("lang", code, max_age=365 * 86400, samesite="lax")
    return response


def int_or_404(value, what="Запись"):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(404, f"{what} не найдена") from None


# ---------------------------------------------------------------- auth
def has_users(conn) -> bool:
    """Real accounts exist (locked demonstration accounts, whose hash starts with "!", do not count)."""
    return conn.execute("SELECT count(*) AS n FROM users WHERE password_hash NOT LIKE '!%'").fetchone()["n"] > 0


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, created: str = "", conn=Depends(get_db)):
    if not has_users(conn):
        return RedirectResponse("/setup", status_code=303)             # first run: create the administrator
    return render(request, "login.html", created=bool(created))


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, conn=Depends(get_db)):
    if has_users(conn):
        return RedirectResponse("/login", status_code=303)
    return render(request, "setup.html", error=None, form={})


@app.post("/setup", response_class=HTMLResponse)
async def setup(request: Request, conn=Depends(get_db)):
    """First run only: the first account is the administrator, with a password chosen by the person who installs."""
    form = await request.form()
    check_csrf(request, form)
    conn.execute("UPDATE schema_migrations SET name = name WHERE 0")      # opens the write transaction: two simultaneous submissions create one account
    if has_users(conn):
        return RedirectResponse("/login", status_code=303)
    login_name, full_name = (form.get("login") or "").strip(), (form.get("full_name") or "").strip()
    password = form.get("password") or ""
    error = None
    if len(login_name) < 3 or " " in login_name:
        error = "Логин: не короче 3 символов, без пробелов"
    elif not full_name:
        error = "Укажите фамилию и инициалы: они попадут в протоколы"
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Пароль: не короче {MIN_PASSWORD_LENGTH} символов"
    elif password != (form.get("password2") or ""):
        error = "Пароли не совпадают"
    if error:
        return render(request, "setup.html", status_code=422, error=error, form={"login": login_name, "full_name": full_name})
    conn.execute("INSERT INTO users(login, full_name, role, password_hash) VALUES (%s, %s, 'admin', %s)",
                 (login_name, full_name, hash_password(password)))
    audit(conn, None, "setup_admin", "users", login_name)
    return RedirectResponse("/login?created=1", status_code=303)


@app.post("/login")
async def login(request: Request, conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    login_name = (form.get("login") or "").strip()
    if throttle.blocked(login_name):
        return render(request, "login.html", status_code=429, error="Слишком много попыток. Подождите несколько минут")
    u = conn.execute("SELECT id, password_hash, is_active FROM users WHERE login = %s", (login_name,)).fetchone()
    if not u or not u["is_active"] or not verify_password(u["password_hash"], form.get("password") or ""):
        throttle.fail(login_name)
        audit(conn, u["id"] if u else None, "login_failed", "users", login_name)
        conn.commit()
        return render(request, "login.html", status_code=401, error="Неверный логин или пароль")
    throttle.reset(login_name)
    request.session.clear()
    request.session["uid"] = u["id"]
    audit(conn, u["id"], "login", "users", u["id"])
    return RedirectResponse("/measurements", status_code=303)


def system_event_for_user(uid, action, entity, entity_id=None, details=None):
    """A record made by the program on behalf of a user outside a request transaction (the sign-out)."""
    conn = connect()
    try:
        audit(conn, uid, action, entity, entity_id, details)
        conn.commit()
    finally:
        conn.close()


@app.post("/logout")
async def logout(request: Request):
    form = await request.form()
    check_csrf(request, form)
    uid = request.session.get("uid")
    if uid:
        system_event_for_user(uid, "logout", "users", uid)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/")
def index(_user=Depends(current_user)):
    return RedirectResponse("/measurements", status_code=303)


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request, user=Depends(current_user)):
    """The user guide (docs/USER_GUIDE.md) inside the application: one source for the repository and for the people at work."""
    import markdown
    path = BASE.parent / "docs" / ("USER_GUIDE.en.md" if current_lang(request) == "en" else "USER_GUIDE.md")
    text = path.read_text(encoding="utf-8") if path.exists() else "Руководство не найдено."
    html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    return render(request, "help.html", user, content=html)


def app_version() -> str:
    """The version of the program: from the image (TRS_VERSION), else from the file VERSION, else dev."""
    v = os.environ.get("TRS_VERSION", "")
    if not v or v == "dev":
        path = BASE.parent / "VERSION"
        v = path.read_text(encoding="utf-8").strip() + "+dev" if path.exists() else "dev"
    return v


def about_context(**extra):
    path = db_path()
    return dict(version=app_version(), data_dir=str(data_dir()), db_file=str(path), log_file=str(applog.log_path()),
                db_mb=round(path.stat().st_size / 1048576, 1) if path.exists() else 0, backup=backups.latest(),
                external=backups.external_status(), **extra)


@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request, user=Depends(current_user)):
    return render(request, "about.html", user, **about_context(update=None))


@app.post("/about/check", response_class=HTMLResponse)
async def about_check(request: Request, user=Depends(current_user)):
    """The only place where the program talks to the internet, and only after this button."""
    form = await request.form()
    check_csrf(request, form)
    return render(request, "about.html", user, **about_context(update=updates.check(app_version())))


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": app_version()}


# ---------------------------------------------------------------- measurements
SESSION_SELECT = """
SELECT s.*, b.modality, b.nominal_energy, b.fff, l.name AS linac, l.model AS linac_model, l.serial_no AS linac_serial,
       el.model AS el_model, el.serial_no AS el_sn, cal.kelec_separate, ch.name AS chamber, cu.serial_no,
       cal.nd_w, cal.k_elec AS cal_k_elec, cal.lab AS cal_lab, cal.voltage_v AS cal_voltage, cal.calibrated_on, cal.q0 AS cal_q0,
       uc.full_name AS creator, ua.full_name AS approver
FROM measurement_sessions s
JOIN beams b ON b.id = s.beam_id
JOIN linacs l ON l.id = b.linac_id
JOIN calibrations cal ON cal.id = s.calibration_id
LEFT JOIN electrometers el ON el.id = cal.electrometer_id
JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
JOIN chambers ch ON ch.id = cu.chamber_id
JOIN users uc ON uc.id = s.created_by
LEFT JOIN users ua ON ua.id = s.approved_by
"""


def get_session_row(conn, sid):
    row = conn.execute(SESSION_SELECT + " WHERE s.id = %s", (int_or_404(sid),)).fetchone()
    if not row:
        raise HTTPException(404, "Запись не найдена")
    return row


def beam_label(b):
    unit = "MV" if b["modality"] == "photon" else "MeV"
    return f"{b['linac']}, {b['nominal_energy']:g} {unit}{' FFF' if b['fff'] else ''}"


def load_choices(conn, modality):
    beams = conn.execute("""SELECT b.*, l.name AS linac, l.model AS linac_model, l.serial_no AS linac_serial, l.city AS city
                            FROM beams b JOIN linacs l ON l.id = b.linac_id
                            WHERE b.modality = %s AND NOT b.archived ORDER BY l.name, b.nominal_energy, b.fff""", (modality,)).fetchall()
    for b in beams:
        b["label"] = beam_label(b)
    supported = set(services.chamber_names()[modality])
    cals = [c for c in conn.execute("""
        SELECT cal.*, ch.name, cu.serial_no, el.model AS el_model, el.serial_no AS el_sn
        FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
        JOIN chambers ch ON ch.id = cu.chamber_id LEFT JOIN electrometers el ON el.id = cal.electrometer_id
        ORDER BY cal.calibrated_on DESC""").fetchall()
        if c["name"] in supported]
    for c in cals:
        c["expired"] = bool(c["valid_until"] and c["valid_until"] < date.today())
        c["nd_warn"] = services.nd_w_warning(c["name"], c["nd_w"])
        info = protocol._chamber_info(modality, c["name"])
        c["wall"] = " ".join(x for x in (str(info.get("wall_material") or ""),
                                         f"{info['wall_thickness']:g} г/см²" if info.get("wall_thickness") else "") if x)
        c["cavity"] = f"{info['cavity_length_cm']:g} см" if info.get("cavity_length_cm") else ""
        c["wallm"] = str(info.get("wall_material") or "")
        c["wallt"] = f"{info['wall_thickness']:g}" if info.get("wall_thickness") else ""
        c["v1"] = f"{c['voltage_v']:g}" if c["voltage_v"] is not None else ""
        c["kelec_eff"] = services.effective_kelec(c)
        c["info"] = "; ".join(x for x in (
            f"стенка: {c['wall']}" if c["wall"] else "", f"длина полости L: {c['cavity']}" if c["cavity"] else "",
            f"ND,w = {c['nd_w']} Гр/нКл", f"kelec = {c['k_elec']}", f"Q0: {c['q0']}",
            f"V1 калибровки: {c['voltage_v']:g} В" if c["voltage_v"] is not None else "",
            f"лаборатория: {c['lab']}" if c["lab"] else "",
            f"калибровка {c['calibrated_on']:%d.%m.%Y}",
            f"действует до {c['valid_until']:%d.%m.%Y}" if c["valid_until"] else "") if x)
    return beams, cals


def _g(v):
    return None if v is None else f"{float(v):g}".replace(".", ",")


def equipment_values(conn, modality, beam, calib):
    """Parameters of worksheet sections 1-3 come from Equipment; the calculation sheet cannot change them.

    Returned values replace whatever the browser sent. Empty equipment fields are left out (the defaults apply),
    so records can still be made for equipment that is only partly described.
    """
    linac = conn.execute("SELECT city FROM linacs WHERE id = %s", (beam["linac_id"],)).fetchone() or {}
    el = conn.execute("SELECT model, serial_no FROM electrometers WHERE id = %s", (calib.get("electrometer_id"),)).fetchone()         if calib.get("electrometer_id") else None
    vals = {
        "city": linac.get("city"), "dose_rate": _g(beam.get("dose_rate_mu")), "field_size": beam.get("field_size"),
        "phantom": beam.get("phantom"), "window_material": beam.get("window_material"),
        "window_thickness": _g(beam.get("window_thickness")), "c_pl": _g(beam.get("c_pl")), "h_pl": _g(beam.get("h_pl")), "zmax": _g(beam.get("zmax")),
        "exp_cgy_mu": _g(beam.get("exp_cgy_mu")), "exp_zref": _g(beam.get("exp_zref")), "exp_source": beam.get("exp_source"),
        "cal_depth": _g(calib.get("cal_depth")), "p0": _g(calib.get("p0")), "t0": _g(calib.get("t0")),
        "cal_rh": _g(calib.get("cal_rh")), "polarity_cal": calib.get("polarity_cal"), "polarity_user": calib.get("polarity_user"),
        "electrometer_range": calib.get("el_range"), "r50_q0": _g(calib.get("r50_q0")),
        "kelec_lab": calib.get("kelec_lab"), "kelec_date": calib["kelec_date"].isoformat() if calib.get("kelec_date") else None,
        "electrometer_model": el["model"] if el else None, "electrometer_sn": el["serial_no"] if el else None,
        "kelec_separate": "1" if calib.get("kelec_separate") else None,
        "cal_pol_corrected": "1" if calib.get("cal_pol_corrected") else None,
    }
    out = {k: str(v) for k, v in vals.items() if v not in (None, "")}
    if modality == "electron":
        out["q0_is_co60"] = "1" if (calib.get("q0") or "Co-60") == "Co-60" else ""
    return out


def pick(conn, table, ident, what):
    row = conn.execute(f"SELECT * FROM {table} WHERE id = %s", (int_or_404(ident, what),)).fetchone()
    if not row:
        raise HTTPException(422, f"{what}: не выбрано")
    return row


def reference_key(modality, geometry, f, beam):
    """Identifies the series of a record in the trends. SSD: the dose at zmax per MU (one definition for all). SAD: the dose at the
    reference point compared with the planning-system value, so the depth, the field and the expected value are part of the key:
    values from different reference conditions are never mixed. SAD without an expected value (the old TMR way): 'SAD|old'."""
    if modality != "photon" or geometry != "SAD":
        return "SSD"
    try:
        expected = float(str(f.get("exp_cgy_mu") or "").replace(",", "."))
    except ValueError:
        expected = None
    if not expected:
        return "SAD|old"
    zref = services.num(f.get("zref"), "zref", required=False, lo=1, hi=20) or 10.0
    field = " ".join((beam.get("field_size") or "").lower().replace("х", "x").replace("×", "x").split())
    return f"SAD|z={zref:g}|{field}|{expected:g}"


def key_label(key):
    """The series of a trend in words."""
    if key == "SSD":
        return "SSD: доза на z_max на 1 MU, норма 1 сГр/MU"
    if key == "SAD|old":
        return "SAD: доза на z_max через TMR (без ожидаемой дозы)"
    parts = key.split("|")
    if len(parts) == 4 and parts[0] == "SAD":
        z = parts[1].removeprefix("z=")
        return (f"SAD: опорная точка на глубине {z.replace('.', ',')} г/см², поле {parts[2] or 'не указано'}, "
                f"ожидаемая доза {parts[3].replace('.', ',')} сГр/MU (система планирования)")
    return key


def prepare(conn, modality, f):
    """Validate the form and compute. Returns (db_values, results, extra)."""
    if modality not in ("photon", "electron"):
        raise HTTPException(404, "Неизвестный тип пучка")
    beam = pick(conn, "beams", f.get("beam_id"), "Пучок")
    if beam["modality"] != modality:
        raise services.InputError("Выбранный пучок не соответствует типу измерения")
    calib = pick(conn, "calibrations", f.get("calibration_id"), "Калибровка камеры")
    if calib["valid_until"] and calib["valid_until"] < date.today():
        raise services.InputError(f"Срок действия калибровки камеры истёк {calib['valid_until']:%d.%m.%Y}: "
                                  "выберите камеру с действующей калибровкой или добавьте новую в разделе «Оборудование»")
    chamber = conn.execute("""SELECT ch.name FROM chamber_units cu JOIN chambers ch ON ch.id = cu.chamber_id
                              WHERE cu.id = %s""", (calib["chamber_unit_id"],)).fetchone()["name"]
    try:
        measured_on = date.fromisoformat(f.get("measured_on") or "")
    except ValueError:
        raise services.InputError("Укажите дату измерения") from None
    if measured_on > date.today():
        raise services.InputError(f"Дата измерения {measured_on:%d.%m.%Y} позже сегодняшней")
    f = services.with_user_series({**f, **equipment_values(conn, modality, beam, calib)})
    for key in ("kelec_separate", "cal_pol_corrected"):       # a snapshot of the equipment state belongs to the record
        f.setdefault(key, "")
    quality, res, extra, _ = services.compute(modality, f, beam, calib, chamber)
    values = dict(
        measured_on=measured_on, beam_id=beam["id"], calibration_id=calib["id"],
        geometry=f.get("geometry", "SSD") if modality == "photon" else "SSD",
        mu=services.num(f.get("mu"), "MU"), pressure_kpa=services.num(f.get("pressure"), "P"),
        temp_c=services.num(f.get("temp"), "T"), humidity_pct=services.num(f.get("humidity"), "RH", required=False, lo=0, hi=100),
        v1=services.num(f.get("v1"), "V1"), v2=services.num(f.get("v2"), "V2"),
        m1_readings=services.readings(f.get("m1"), "M1"), m2_readings=services.readings(f.get("m2"), "M2"),
        m_plus_readings=services.readings(f.get("m_plus"), "M+", required=False),
        m_minus_readings=services.readings(f.get("m_minus"), "M-", required=False),
        beam_quality=quality, pdd_zref=services.num(f.get("pdd_zref"), "PDD", required=False),
        tmr_zref=services.num(f.get("tmr_zref"), "TMR", required=False), note=(f.get("note") or "").strip() or None,
        ref_key=reference_key(modality, f.get("geometry", "SSD"), f, beam),
    )
    return values, res, extra


def save_results(conn, sid, res):
    cols = list(res)
    conn.execute(
        f"INSERT INTO results(session_id, {', '.join(cols)}) VALUES (%s, {', '.join(['%s'] * len(cols))}) "
        f"ON CONFLICT (session_id) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in cols)}, computed_at = now()",
        [sid] + [res[c] for c in cols])


def form_dict(form):
    return {k: v for k, v in form.items() if isinstance(v, str)}


@app.get("/measurements", response_class=HTMLResponse)
def measurements(request: Request, status: str = "", user=Depends(current_user), conn=Depends(get_db)):
    where, params = "", []
    if status in STATUS_LABELS:
        where, params = "WHERE s.status = %s", [status]
    rows = conn.execute(f"""SELECT s.id, s.protocol_no, s.measured_on, s.status, s.created_by, b.modality, b.nominal_energy, b.fff,
        l.name AS linac, uc.full_name AS creator, r.dw_zmax, r.deviation_pct
        FROM measurement_sessions s JOIN beams b ON b.id = s.beam_id JOIN linacs l ON l.id = b.linac_id
        JOIN users uc ON uc.id = s.created_by LEFT JOIN results r ON r.session_id = s.id
        {where} ORDER BY s.measured_on DESC, s.id DESC LIMIT 3000""", params).fetchall()
    for r in rows:
        r["label"] = beam_label(r)
    pending = conn.execute("SELECT count(*) AS n FROM measurement_sessions WHERE status = 'submitted'").fetchone()["n"]
    return render(request, "list.html", user, rows=rows, status=status, pending=pending,
                  reminders=calibration_reminders(conn, date.today()))


@app.get("/measurements/new", response_class=HTMLResponse)
def new_form(request: Request, modality: str = "photon", user=Depends(require("physicist", "admin")),
             conn=Depends(get_db)):
    if modality not in ("photon", "electron"):
        raise HTTPException(404, "Неизвестный тип пучка")
    beams, cals = load_choices(conn, modality)
    return render(request, "form.html", user, modality=modality, beams=beams, cals=cals,
                  f={"measured_on": date.today().isoformat(), "geometry": "SSD", "humidity": "50"}, is_new=True,
                  action="/measurements", title="Новое измерение")


REFERENCE_FIELDS = ("m1_v1", "m_plus", "m_minus", "m2", "v1", "v2", "pulsed_scanned")
# what "make these values the reference of the beam" stores: the quality inputs (section 1), the series M and MU (section 3),
# polarity (iii) and recombination (iv)
REFERENCE_SAVED = REFERENCE_FIELDS + ("tpr", "pdd10", "pdd20", "r50", "mu", "m1")
REFERENCE_SERIES = ("m1", "m1_v1", "m_plus", "m_minus", "m2")
REFERENCE_NUMBERS = {"tpr": (0.3, 1.0), "pdd10": (10, 100), "pdd20": (5, 100), "r50": (0.5, 20), "mu": (1, 100000),
                     "v1": (-1500, 1500), "v2": (-1500, 1500)}


def chamber_unit_of(conn, calibration_id):
    row = conn.execute("SELECT chamber_unit_id FROM calibrations WHERE id = %s", (calibration_id,)).fetchone()         if str(calibration_id).isdigit() else None
    return row["chamber_unit_id"] if row else None


@app.get("/measurements/reference")
def reference_series(beam_id: str = "", calibration_id: str = "", source: str = "auto", user=Depends(require("physicist", "admin")),
                     conn=Depends(get_db)):
    """Reference values for a new measurement: the ones a physicist declared for this beam and chamber (source=saved),
    otherwise the first approved measurement of the beam (source=first).

    The corrections (iii) polarity and (iv) recombination are determined once per beam and chamber; later checks reuse them,
    but the user may change them.
    """
    bid = int_or_404(beam_id, "Пучок")
    unit = chamber_unit_of(conn, calibration_id)
    saved = conn.execute("""SELECT r.data, r.set_at, u.full_name FROM beam_reference r JOIN users u ON u.id = r.set_by
                            WHERE r.beam_id = %s AND r.chamber_unit_id = %s""", (bid, unit)).fetchone() if unit else None
    if saved and source in ("auto", "saved"):
        return JSONResponse({"found": True, "kind": "saved", "date": saved["set_at"].strftime("%d.%m.%Y"), "by": saved["full_name"],
                             **{k: saved["data"].get(k, "") for k in REFERENCE_SAVED}})
    if source == "saved":
        return JSONResponse({"found": False, "kind": "saved"})
    base = """SELECT s.*, b.modality FROM measurement_sessions s JOIN beams b ON b.id = s.beam_id
              WHERE s.beam_id = %s AND s.status = 'approved' {extra} ORDER BY s.measured_on, s.id LIMIT 1"""
    row = None
    if calibration_id.isdigit():
        row = conn.execute(base.format(extra="""AND s.calibration_id IN (SELECT c2.id FROM calibrations c2 WHERE
                           c2.chamber_unit_id = (SELECT chamber_unit_id FROM calibrations WHERE id = %s))"""),
                           (bid, int(calibration_id))).fetchone()
    if not row:
        row = conn.execute(base.format(extra=""), (bid,)).fetchone()
    if not row:
        return JSONResponse({"found": False, "kind": "first"})
    f = form_values(row)
    f["m1_v1"] = f.get("m1_v1") or f.get("m1", "")
    f["pulsed_scanned"] = f.get("pulsed_scanned") or ""
    return JSONResponse({"found": True, "kind": "first", "record": row["id"], "date": row["measured_on"].strftime("%d.%m.%Y"),
                         **{k: f.get(k, "") for k in REFERENCE_SAVED}})


@app.post("/measurements/reference")
async def save_reference(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    """The values of the open worksheet become the reference of this beam with this chamber unit."""
    form = await request.form()
    check_csrf(request, form)
    bid = int_or_404(form.get("beam_id"), "Пучок")
    unit = chamber_unit_of(conn, form.get("calibration_id"))
    if not unit or not conn.execute("SELECT 1 FROM beams WHERE id = %s", (bid,)).fetchone():
        raise HTTPException(404, "Пучок или калибровка не найдены")
    data = {}
    try:
        for name in REFERENCE_SAVED:
            raw = (form.get(name) or "").strip()
            if not raw:
                continue
            if name in REFERENCE_SERIES:
                services.readings(raw, name)
            elif name in REFERENCE_NUMBERS:
                lo, hi = REFERENCE_NUMBERS[name]
                services.num(raw, name, lo=lo, hi=hi)
            data[name] = raw
    except services.InputError as e:
        raise HTTPException(422, str(e)) from None
    if not any(data.get(k) for k in ("m_plus", "m_minus", "m2")):
        raise HTTPException(422, "Заполните показания (iii) и (iv): иначе опорных значений нет")
    from app.db import Jsonb
    conn.execute("""INSERT INTO beam_reference(beam_id, chamber_unit_id, data, set_by) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (beam_id, chamber_unit_id) DO UPDATE SET data = EXCLUDED.data, set_by = EXCLUDED.set_by, set_at = now()""",
                 (bid, unit, Jsonb(data), user["id"]))
    audit(conn, user["id"], "beam_reference", "beams", bid, {"chamber_unit_id": unit, "fields": sorted(data)})
    return JSONResponse({"ok": True})


@app.post("/measurements/preview", response_class=HTMLResponse)
async def preview(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    f = form_dict(form)
    modality = f.get("modality", "")
    if modality not in ("photon", "electron"):
        raise HTTPException(404, "Неизвестный тип пучка")
    cells, res, error, exp_cgy_mu = {}, None, None, None
    try:
        beam = conn.execute("SELECT * FROM beams WHERE id = %s", (int(f.get("beam_id") or 0),)).fetchone()
        calib = conn.execute("SELECT * FROM calibrations WHERE id = %s", (int(f.get("calibration_id") or 0),)).fetchone()
        chamber = None
        if calib:
            chamber = conn.execute("""SELECT ch.name FROM chamber_units cu JOIN chambers ch ON ch.id = cu.chamber_id
                                      WHERE cu.id = %s""", (calib["chamber_unit_id"],)).fetchone()["name"]
        if beam and beam["modality"] == modality:
            if calib:
                f = services.with_user_series({**f, **equipment_values(conn, modality, beam, calib)})
            cells = services.live(modality, f, beam, calib, chamber)
    except ValueError:
        pass
    try:
        _, res, extra = prepare(conn, modality, f)
        exp_cgy_mu = extra["form"].get("exp_cgy_mu") if res.get("dw_zmax") is None else None
        from app import protocol as pr
        cells.update(mq=pr.sci(res["m_corrected"]), dwref=pr.f(res["dw_zref"], 6), dwmax=pr.f(res["dw_zmax"], 6),
                     dev=pr.f(res["deviation_pct"], 2), kq=pr.f(res["k_q"], 4), kelec=pr.f(res["k_elec"], 4))
    except services.InputError as e:
        error = str(e)
    except HTTPException:
        error = "Выберите пучок и калибровку камеры"
    if calib:
        from app import protocol as pr
        cells.setdefault("kelec", pr.f(services.effective_kelec(calib), 4))
    drift = {}
    for key, name in (("dr_m1", "m1"), ("dr_plus", "m_plus"), ("dr_minus", "m_minus"), ("dr_m1ks", "m1_v1"), ("dr_m2", "m2")):
        try:
            stats = services.series_stats(services.readings(f.get(name), name, required=False) or [])
        except services.InputError:
            stats = None
        if stats:
            cells[key] = f"{stats['drift_pct']:+.2f} % ".replace(".", ",") + ("" if stats["status"] == "ok" else "!")
            drift[key] = stats["status"]
    ids = ("q", "qsrc", "r50w", "zref", "m1avg", "m2avg", "mpavg", "mmavg", "muavg", "m1ksavg", "dr_m1", "dr_plus", "dr_minus", "dr_m1ks", "dr_m2", "mper", "ktp", "kpol", "vr", "mr", "a0", "a1", "a2",
           "ks", "rid", "L", "kvol", "kq", "kelec", "mq", "dwref", "dwmax", "dev")
    cells = {i: cells.get(i, "—") for i in ids}                     # cleared fields reset their cells
    return render(request, "_result.html", user, res=res, error=error, cells=cells, drift=drift, exp_cgy_mu=exp_cgy_mu)


@app.post("/measurements")
async def create(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    f = form_dict(form)
    modality = f.get("modality", "")
    try:
        values, res, extra = prepare(conn, modality, f)
    except services.InputError as e:
        beams, cals = load_choices(conn, modality)
        return render(request, "form.html", user, status_code=422, modality=modality, beams=beams, cals=cals, f=f,
                      error=str(e), action="/measurements", title="Новое измерение", is_new=True)
    from app.db import Jsonb
    cols = list(values)
    row = conn.execute(
        f"INSERT INTO measurement_sessions({', '.join(cols)}, created_by, extra) "
        f"VALUES ({', '.join(['%s'] * len(cols))}, %s, %s) RETURNING id",
        [values[c] for c in cols] + [user["id"], Jsonb(extra)]).fetchone()
    save_results(conn, row["id"], res)
    audit(conn, user["id"], "create", "measurement", row["id"], {"modality": modality})
    return RedirectResponse(f"/measurements/{row['id']}", status_code=303)


@app.get("/measurements/{sid}", response_class=HTMLResponse)
def detail(request: Request, sid: str, user=Depends(current_user), conn=Depends(get_db)):
    s = get_session_row(conn, sid)
    res = conn.execute("SELECT * FROM results WHERE session_id = %s", (s["id"],)).fetchone()
    mine = s["created_by"] == user["id"]
    return render(request, "detail.html", user, s=s, res=res, beam=beam_label(s), mine=mine,
                  can_edit=mine and s["status"] in ("draft", "returned"),
                  can_decide=can_review(user["role"]) and not mine and s["status"] == "submitted",
                  can_supersede=can_create(user["role"]) and s["status"] == "approved",
                  can_delete=s["status"] in ("draft", "returned") and (mine or user["role"] == "admin") and can_create(user["role"]),
                  can_void=user["role"] == "admin" and s["status"] == "approved")


def unc_choice(value: str) -> str:
    return value if value in ("short", "full", "none") else "short"


def protocol_page(conn, user, sid, kind):
    s = get_session_row(conn, sid)
    res = conn.execute("SELECT * FROM results WHERE session_id = %s", (s["id"],)).fetchone()
    if not res:
        raise HTTPException(409, "Нет рассчитанного результата: протокол сформировать нельзя")
    audit(conn, user["id"], kind, "measurement", s["id"])
    # deviation history of this beam up to (and including) the measurement: approved + imported records
    history = [(p.on, p.deviation_pct) for p in trend_points(conn, s) if p.on <= s["measured_on"]]
    if s["status"] != "approved":
        history.append((s["measured_on"], float(res["deviation_pct"])))        # not in the trend yet
    periods = beam_periods(conn, s["beam_id"])[0]
    return s, res, protocol.build(s, res, history, periods, unc_settings=unc_settings(conn, s["modality"]))


@app.get("/measurements/{sid}/print", response_class=HTMLResponse)
def print_protocol(request: Request, sid: str, unc: str = "short", user=Depends(current_user), conn=Depends(get_db)):
    """unc: how much of the uncertainty analysis goes into the protocol: short (one page, default), full, none."""
    s, res, p = protocol_page(conn, user, sid, "print")
    return render(request, "protocol.html", user, s=s, res=res, v=p, screen=True, unc_mode=unc_choice(unc))


@app.get("/measurements/{sid}/pdf")
def pdf_protocol(request: Request, sid: str, unc: str = "short", user=Depends(current_user), conn=Depends(get_db)):
    s, res, p = protocol_page(conn, user, sid, "pdf")
    html = render(request, "protocol.html", user, s=s, res=res, v=p, screen=False,
                  unc_mode=unc_choice(unc)).body.decode("utf-8")
    try:
        pdf = html_to_pdf(html)
    except PdfUnavailable:
        raise HTTPException(503, "Генерация PDF недоступна: на компьютере не найден Microsoft Edge или Chrome. "
                                 "Используйте «Печать → Сохранить как PDF».") from None
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="TRS398-protocol-{s["id"]}.pdf"'})


def form_values(s):
    """Values for the entry form of an existing record.

    The stored columns are authoritative (records made by the importer or the demo seeder have only those);
    extra.form supplies what has no column (field size, polarity, electrometer range, ...).
    """
    def g(v):
        return "" if v is None else f"{float(v):g}".replace(".", ",")

    def series(vals):
        return " ".join(g(v) for v in (vals or []))

    f = dict(s["extra"].get("form", {}))
    f.update(measured_on=s["measured_on"].isoformat(), beam_id=str(s["beam_id"]), calibration_id=str(s["calibration_id"]),
             note=s["note"] or "", geometry=s["geometry"], mu=g(s["mu"]), pressure=g(s["pressure_kpa"]),
             temp=g(s["temp_c"]), humidity=g(s["humidity_pct"]), v1=g(s["v1"]), v2=g(s["v2"]),
             m1=series(s["m1_readings"]), m2=series(s["m2_readings"]), m_plus=series(s["m_plus_readings"]),
             m_minus=series(s["m_minus_readings"]), pdd_zref=g(s["pdd_zref"]), tmr_zref=g(s["tmr_zref"]))
    if s["modality"] == "electron":
        f["r50"] = g(s["beam_quality"])
    elif not f.get("pdd10") and not f.get("tpr"):      # a TPR derived from PDD stays derived: changing PDD must update it
        f["tpr"] = g(s["beam_quality"])
    return {k: v for k, v in f.items() if v not in (None, "")}


@app.get("/measurements/{sid}/edit", response_class=HTMLResponse)
def edit_form(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    s = get_session_row(conn, sid)
    if s["created_by"] != user["id"] or s["status"] not in ("draft", "returned"):
        raise HTTPException(403, "Редактировать можно только свой черновик или возвращённую запись")
    beams, cals = load_choices(conn, s["modality"])
    f = form_values(s)
    return render(request, "form.html", user, modality=s["modality"], beams=beams, cals=cals, f=f,
                  action=f"/measurements/{s['id']}/edit", title=f"Правка протокола №{s['protocol_no']}", protocol_no=s["protocol_no"])


@app.post("/measurements/{sid}/edit")
async def edit(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    if s["created_by"] != user["id"] or s["status"] not in ("draft", "returned"):
        raise HTTPException(403, "Редактировать можно только свой черновик или возвращённую запись")
    f = form_dict(form)
    try:
        values, res, extra = prepare(conn, s["modality"], f)
    except services.InputError as e:
        beams, cals = load_choices(conn, s["modality"])
        return render(request, "form.html", user, status_code=422, modality=s["modality"], beams=beams, cals=cals,
                      f=f, error=str(e), action=f"/measurements/{s['id']}/edit", title=f"Правка записи №{s['id']}")
    from app.db import Jsonb
    cols = list(values)
    conn.execute(f"UPDATE measurement_sessions SET {', '.join(f'{c} = %s' for c in cols)}, extra = %s, "
                 f"status = 'draft', review_comment = NULL WHERE id = %s",
                 [values[c] for c in cols] + [Jsonb(extra), s["id"]])
    save_results(conn, s["id"], res)
    audit(conn, user["id"], "edit", "measurement", s["id"],
          {"protocol_no": s["protocol_no"], "changes": auditlog.as_json(auditlog.diff(s, values))})
    return RedirectResponse(f"/measurements/{s['id']}", status_code=303)


async def _transition(request, sid, user, conn, action):
    form = await request.form()
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    comment = (form.get("comment") or "").strip()
    if action == "submit":
        if s["created_by"] != user["id"] or s["status"] not in ("draft", "returned"):
            raise HTTPException(403, "Отправить на проверку может автор черновика")
        if not conn.execute("SELECT 1 FROM results WHERE session_id = %s", (s["id"],)).fetchone():
            raise HTTPException(409, "Нет рассчитанного результата")
        conn.execute("UPDATE measurement_sessions SET status = 'submitted' WHERE id = %s", (s["id"],))
    else:
        if not can_review(user["role"]):
            raise HTTPException(403, "Недостаточно прав")
        if s["status"] != "submitted":
            raise HTTPException(409, "Запись не находится на проверке")
        if s["created_by"] == user["id"]:
            raise HTTPException(403, "Нельзя утверждать или возвращать собственную запись (правило двух лиц)")
        if action == "approve":
            conn.execute("""UPDATE measurement_sessions SET status = 'approved', approved_by = %s, approved_at = now(),
                            review_comment = NULLIF(%s, '') WHERE id = %s""", (user["id"], comment, s["id"]))
            if s["supersedes_id"]:
                conn.execute("UPDATE measurement_sessions SET status = 'superseded' WHERE id = %s",
                             (s["supersedes_id"],))
        else:
            if len(comment) < 3:
                raise HTTPException(422, "При возврате укажите комментарий")
            conn.execute("UPDATE measurement_sessions SET status = 'returned', review_comment = %s WHERE id = %s",
                         (comment, s["id"]))
    audit(conn, user["id"], action, "measurement", s["id"], {"comment": comment} if comment else {})
    return RedirectResponse(f"/measurements/{s['id']}", status_code=303)


@app.post("/measurements/{sid}/submit")
async def submit(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    return await _transition(request, sid, user, conn, "submit")


@app.post("/measurements/{sid}/approve")
async def approve(request: Request, sid: str, user=Depends(require("reviewer", "admin")), conn=Depends(get_db)):
    return await _transition(request, sid, user, conn, "approve")


@app.post("/measurements/{sid}/return")
async def return_(request: Request, sid: str, user=Depends(require("reviewer", "admin")), conn=Depends(get_db)):
    return await _transition(request, sid, user, conn, "return")


@app.post("/measurements/{sid}/supersede")
async def supersede(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    reason = (form.get("reason") or "").strip()
    if s["status"] != "approved":
        raise HTTPException(409, "Заменить можно только утверждённую запись")
    if len(reason) < 5:
        raise HTTPException(422, "Укажите причину замены (не короче 5 символов)")
    from app.db import Jsonb
    new = conn.execute("""INSERT INTO measurement_sessions(measured_on, beam_id, calibration_id, geometry, mu,
            pressure_kpa, temp_c, humidity_pct, v1, v2, m1_readings, m2_readings, m_plus_readings, m_minus_readings,
            beam_quality, pdd_zref, tmr_zref, note, created_by, extra, supersedes_id, supersede_reason, ref_key)
        SELECT measured_on, beam_id, calibration_id, geometry, mu, pressure_kpa, temp_c, humidity_pct, v1, v2,
            m1_readings, m2_readings, m_plus_readings, m_minus_readings, beam_quality, pdd_zref, tmr_zref, note,
            %s, extra, id, %s, ref_key FROM measurement_sessions WHERE id = %s RETURNING id""",
                        (user["id"], reason, s["id"])).fetchone()
    old = conn.execute("SELECT * FROM results WHERE session_id = %s", (s["id"],)).fetchone()
    if old:
        old.pop("session_id"), old.pop("computed_at")
        save_results(conn, new["id"], old)
    audit(conn, user["id"], "supersede", "measurement", s["id"], {"new_id": new["id"], "reason": reason})
    return RedirectResponse(f"/measurements/{new['id']}/edit", status_code=303)


@app.post("/measurements/{sid}/delete")
async def delete_measurement(request: Request, sid: str, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    """A draft or a returned record goes away (the author or an admin); the protocol number is not reused and the audit log keeps it."""
    form = await request.form()
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    if s["status"] not in ("draft", "returned"):
        raise HTTPException(409, "Удалить можно только черновик или возвращённую запись; утверждённую можно аннулировать")
    if s["created_by"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "Удалить запись может только её автор или администратор")
    try:
        dbops.delete_draft(conn, s["id"], user["id"])
    except dbops.MaintenanceError as e:
        raise HTTPException(409, str(e)) from None
    return RedirectResponse("/measurements", status_code=303)


@app.post("/measurements/{sid}/void")
async def void_measurement(request: Request, sid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    """An approved record is annulled, never deleted: it leaves trends and budgets, the protocol says ANNULLED."""
    form = await request.form()
    check_csrf(request, form)
    s = get_session_row(conn, sid)
    reason = (form.get("reason") or "").strip()
    if s["status"] != "approved":
        raise HTTPException(409, "Аннулировать можно только утверждённую запись")
    if len(reason) < 5:
        raise HTTPException(422, "Укажите причину аннулирования (не короче 5 символов)")
    conn.execute("""UPDATE measurement_sessions SET status = 'voided', void_reason = %s, voided_by = %s, voided_at = now()
                    WHERE id = %s""", (reason, user["id"], s["id"]))
    restored = None
    if s["supersedes_id"]:                  # the correction is annulled: the record it replaced is valid again
        done = conn.execute("UPDATE measurement_sessions SET status = 'approved' WHERE id = %s AND status = 'superseded' RETURNING id",
                            (s["supersedes_id"],)).fetchone()
        restored = done["id"] if done else None
    audit(conn, user["id"], "void", "measurement", s["id"], {"protocol_no": s["protocol_no"], "reason": reason, "restored_id": restored})
    return RedirectResponse(f"/measurements/{s['id']}", status_code=303)


# ---------------------------------------------------------------- trends
def trend_keys(conn, beam):
    """The series of a beam: [(ref_key, records, last date)], the one with the latest record first. SSD and SAD records with
    different reference conditions are different series."""
    return conn.execute("""SELECT ref_key, count(*) AS n, max(measured_on) AS last_on FROM v_trend
        WHERE linac = %s AND modality = %s AND nominal_energy = %s AND fff = %s GROUP BY ref_key ORDER BY max(measured_on) DESC, ref_key""",
                        (beam["linac"], beam["modality"], beam["nominal_energy"], beam["fff"])).fetchall()


def trend_points(conn, beam, key=None):
    """Points of one series: `key`, else the series of the record itself (a session row carries ref_key), else the latest one."""
    key = key or beam.get("ref_key") or next((k["ref_key"] for k in trend_keys(conn, beam)[:1]), None)
    rows = conn.execute("""SELECT measured_on, deviation_pct, source FROM v_trend
        WHERE linac = %s AND modality = %s AND nominal_energy = %s AND fff = %s AND ref_key IS NOT DISTINCT FROM %s
        ORDER BY measured_on, source, record_id""",
                        (beam["linac"], beam["modality"], beam["nominal_energy"], beam["fff"], key)).fetchall()
    return [spc.Point(r["measured_on"], float(r["deviation_pct"])) for r in rows]


def beam_periods(conn, beam_id):
    """Baseline periods of a beam: [(from, to)] and the rows for the page."""
    rows = conn.execute("""SELECT bl.*, u.full_name AS who FROM spc_baseline bl LEFT JOIN users u ON u.id = bl.set_by
                           WHERE bl.beam_id = %s ORDER BY bl.from_date""", (beam_id,)).fetchall()
    return [(r["from_date"], r["to_date"]) for r in rows], rows


def plot_data(summary):
    """Plain data for the interactive (Plotly) trend chart; the server-side SVG stays as the fallback."""
    return {
        "x": [p.on.isoformat() for p in summary.points],
        "y": [round(p.deviation_pct, 4) for p in summary.points],
        "signal": [p.signal or "" for p in summary.points],
        "cusum": [p.cusum_signal or "" for p in summary.points],
        "cusum_plus": [round(p.cusum_plus, 4) for p in summary.points], "cusum_minus": [round(p.cusum_minus, 4) for p in summary.points],
        "h": round(5 * summary.sigma, 4) if summary.sigma else None,
        "pre": [bool(p.pre) for p in summary.points], "segment": [p.segment for p in summary.points],
        "segments": [{"start": g["start"].isoformat(), "end": g["end"].isoformat() if g["end"] else None, "cl": g["cl"], "sigma": g["sigma"],
                      "h": round(5 * g["sigma"], 4) if g["sigma"] else None} for g in summary.segments],
        "cl": summary.cl, "sigma": summary.sigma,
        "tolerance": spc.ACTION_PCT, "observe": spc.OBSERVE_PCT,
    }


@app.get("/trends", response_class=HTMLResponse)
def trends(request: Request, beam_id: str = "", cond: str = "", user=Depends(current_user), conn=Depends(get_db)):
    beams = conn.execute("SELECT b.*, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id "
                         "ORDER BY l.name, b.modality, b.nominal_energy, b.fff").fetchall()
    for b in beams:
        b["label"] = ("γ " if b["modality"] == "photon" else "e⁻ ") + beam_label(b)
    ctx = dict(beams=beams, beam=None, summary=None, chart="", period_rows=[], baseline_fixed=False, signals=[])
    if beam_id:
        beam = next((b for b in beams if str(b["id"]) == beam_id), None)
        if not beam:
            raise HTTPException(404, "Пучок не найден")
        keys = trend_keys(conn, beam)
        key = cond if cond in [k["ref_key"] for k in keys] else (keys[0]["ref_key"] if keys else None)
        pts = trend_points(conn, beam, key)
        periods, period_rows = beam_periods(conn, beam["id"])
        summary = spc.analyse(pts, periods=periods)
        ctx.update(plot=plot_data(summary), beam=beam, summary=summary, chart=control_chart(summary), period_rows=period_rows,
                   baseline_fixed=bool(summary.segments), today=date.today(),
                   series=[dict(key=k["ref_key"], label=key_label(k["ref_key"]), n=k["n"], last=k["last_on"]) for k in keys], series_key=key,
                   signals=[p for p in summary.points if p.signal or p.cusum_signal][-15:])
    return render(request, "trends.html", user, **ctx)


@app.get("/trends/export")
def trends_export(request: Request, beam_id: str, cond: str = "", fmt: str = "xlsx", user=Depends(current_user), conn=Depends(get_db)):
    """The series of one beam as a CSV or an Excel file: the points with the limits and the signals, the summary, the baseline periods."""
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(422, "Формат: csv или xlsx")
    beam = conn.execute("SELECT b.*, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id WHERE b.id = %s",
                        (int_or_404(beam_id, "Пучок"),)).fetchone()
    if not beam:
        raise HTTPException(404, "Пучок не найден")
    keys = trend_keys(conn, beam)
    key = cond if cond in [k["ref_key"] for k in keys] else (keys[0]["ref_key"] if keys else None)
    periods, _rows = beam_periods(conn, beam["id"])
    summary = spc.analyse(trend_points(conn, beam, key), periods=periods)
    if summary.n == 0:
        raise HTTPException(404, "Для этого пучка нет данных для выгрузки")
    records = conn.execute("""SELECT t.source, t.record_id, t.dw_zmax, s.protocol_no FROM v_trend t
        LEFT JOIN measurement_sessions s ON t.source = 'measured' AND s.id = t.record_id
        WHERE t.linac = %s AND t.modality = %s AND t.nominal_energy = %s AND t.fff = %s AND t.ref_key IS NOT DISTINCT FROM %s
        ORDER BY t.measured_on, t.source, t.record_id""", (beam["linac"], beam["modality"], beam["nominal_energy"], beam["fff"], key)).fetchall()
    lang = current_lang(request)
    name = f"{beam['linac']}, {beam_label(beam)}"
    points = [trend_export.POINT_HEAD] + trend_export.point_rows(summary, records)
    if fmt == "csv":
        body, media, ext = trend_export.to_csv(points, lang), "text/csv; charset=utf-8", "csv"
    else:
        sheets = [("Данные", points), ("Сводка", trend_export.summary_rows(name, key_label(key), summary, user["full_name"], date.today())),
                  ("Базовые периоды", trend_export.period_rows(summary))]
        body = trend_export.to_xlsx(sheets, lang)
        media, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    audit(conn, user["id"], "trends_export", "beams", beam["id"], {"format": ext, "rows": summary.n, "series": key_label(key)})
    from urllib.parse import quote
    pretty = quote(f"trend {name}.{ext}".replace(",", ""))
    return Response(body, media_type=media, headers={"Content-Disposition": f"attachment; filename=\"trend.{ext}\"; filename*=UTF-8''{pretty}"})


COMPARE_MODALITIES = {"all": "фотоны и электроны", "photon": "только фотоны", "electron": "только электроны"}
COMPARE_PERIODS = {"": "весь период", "24": "последние 24 мес", "12": "последние 12 мес", "6": "последние 6 мес"}


@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request, linac_id: str = "", modality: str = "all", months: str = "",
                 user=Depends(current_user), conn=Depends(get_db)):
    """Trends of several energies of one linac side by side, with a search for a common cause."""
    if modality not in COMPARE_MODALITIES or months not in COMPARE_PERIODS:
        raise HTTPException(422, "Неверные параметры сравнения")
    linacs = conn.execute("""SELECT l.id, l.name, (SELECT count(DISTINCT t.modality || '|' || t.nominal_energy || '|' || t.fff) FROM v_trend t
                             WHERE t.linac = l.name) AS n_beams FROM linacs l ORDER BY l.name""").fetchall()
    ctx = dict(linacs=linacs, linac=None, modality=modality, months=months, modalities=COMPARE_MODALITIES,
               periods=COMPARE_PERIODS, summaries=[], hints=[], flagged=[], corr_labels=[], plot={},
               min_beams=compare.MIN_BEAMS, shift=str(compare.SHIFT_PCT).replace(".", ","))
    if not linacs:
        return render(request, "compare.html", user, **ctx)
    linac = next((l for l in linacs if str(l["id"]) == linac_id), None) if linac_id else max(linacs, key=lambda l: l["n_beams"])
    if linac is None:
        raise HTTPException(404, "Аппарат не найден")
    ctx["linac"] = linac
    since = None
    if months:
        today = date.today()
        total = today.year * 12 + today.month - 1 - int(months)
        since = date(total // 12, total % 12 + 1, 1)

    beams = conn.execute("""SELECT b.id, b.modality, b.nominal_energy, b.fff, l.name AS linac FROM beams b
                            JOIN linacs l ON l.id = b.linac_id WHERE l.id = %s ORDER BY b.modality, b.nominal_energy, b.fff""",
                         (linac["id"],)).fetchall()
    series, baselines = {}, {}
    for b in beams:
        if modality != "all" and b["modality"] != modality:
            continue
        pts = trend_points(conn, b)
        if since:
            pts = [p for p in pts if p.on >= since]
        if not pts:
            continue
        label = f"{'γ' if b['modality'] == 'photon' else 'e⁻'} {b['nominal_energy']:g} {'MV' if b['modality'] == 'photon' else 'MeV'}" \
                f"{' FFF' if b['fff'] else ''}"
        series[label] = pts
        periods = beam_periods(conn, b["id"])[0]
        if periods:
            baselines[label] = periods
    if not series:
        return render(request, "compare.html", user, **ctx)

    mths, matrix = compare.align(series)
    common = compare.common_mode(mths, matrix)
    corr_labels, corr = compare.correlations(mths, matrix)
    ctx.update(
        summaries=[compare.beam_summary(label, pts, baselines.get(label)) for label, pts in series.items()],
        hints=compare.interpretation(common, corr_labels, corr), flagged=[c for c in common if c.flagged],
        corr_labels=corr_labels,
        plot={"series": [{"label": label, "x": [p.on.isoformat() for p in pts], "y": [round(p.deviation_pct, 3) for p in pts]}
                         for label, pts in series.items()],
              "common": {"x": [c.month + "-15" for c in common], "y": [round(c.mean, 3) for c in common]},
              "months": mths, "labels": list(matrix), "matrix": [[None if v is None else round(v, 3) for v in row] for row in matrix.values()],
              "corr_labels": corr_labels, "corr": [[None if v is None else round(v, 3) for v in row] for row in corr]})
    return render(request, "compare.html", user, **ctx)


@app.post("/trends/baseline")
async def set_baseline(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    beam_id = int_or_404(form.get("beam_id"), "Пучок")
    try:
        d1, d2 = date.fromisoformat(form.get("from_date") or ""), date.fromisoformat(form.get("to_date") or "")
    except ValueError:
        raise HTTPException(422, "Укажите даты начала и конца базового периода") from None
    if d2 < d1:
        raise HTTPException(422, "Конец периода раньше начала")
    conn.execute("""INSERT INTO spc_baseline(beam_id, from_date, to_date, set_by) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (beam_id, from_date) DO UPDATE SET to_date = EXCLUDED.to_date,
                    set_by = EXCLUDED.set_by, set_at = now()""", (beam_id, d1, d2, user["id"]))
    audit(conn, user["id"], "set_baseline", "spc_baseline", beam_id, {"from": str(d1), "to": str(d2)})
    return RedirectResponse(f"/trends?beam_id={beam_id}", status_code=303)


@app.post("/trends/baseline/delete")
async def delete_baseline(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    row = conn.execute("DELETE FROM spc_baseline WHERE id = %s RETURNING beam_id, from_date, to_date",
                       (int_or_404(form.get("id"), "Период"),)).fetchone()
    if not row:
        raise HTTPException(404, "Базовый период не найден")
    audit(conn, user["id"], "delete_baseline", "spc_baseline", row["beam_id"], {"from": str(row["from_date"]), "to": str(row["to_date"])})
    return RedirectResponse(f"/trends?beam_id={row['beam_id']}", status_code=303)



# ---------------------------------------------------------------- uncertainty
def _opt_date(text):
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        raise HTTPException(422, "Дата в формате ГГГГ-ММ-ДД") from None


def _opt_float(text, default, name, lo, hi):
    try:
        v = float((text or "").replace(",", ".")) if text else default
    except ValueError:
        raise HTTPException(422, f"«{name}»: не число") from None
    if not lo <= v <= hi:
        raise HTTPException(422, f"«{name}»: допустимо {lo}–{hi}")
    return v


def unc_settings(conn, modality):
    """(overrides {code: u}, extras [..]) of the Type B uncertainty budget of a modality, as edited by the users."""
    rows = conn.execute("SELECT * FROM uncertainty_settings WHERE modality = %s AND active ORDER BY id", (modality,)).fetchall()
    overrides = {r["code"]: float(r["u_pct"]) for r in rows if not r["is_extra"]}
    extras = [dict(code=r["code"], name=r["name"], stage=r["stage"], u_pct=float(r["u_pct"]), note=r["note"],
                   dist=r["dist"] or "", how=r["how"] or "")
              for r in rows if r["is_extra"]]
    return overrides, extras


def unc_back(form) -> str:
    back = form.get("back") or "/uncertainty"
    return back if back.startswith("/uncertainty") else "/uncertainty"


def unc_number(text, label):
    try:
        return services.num(text, label, required=True, lo=0, hi=10)
    except services.InputError as e:
        raise HTTPException(422, str(e)) from None


@app.post("/uncertainty/settings")
async def unc_save(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    """Save the values of the budget table: a value equal to the standard one switches the change off."""
    form = await request.form()
    check_csrf(request, form)
    modality = form.get("modality")
    if modality not in ("photon", "electron"):
        raise HTTPException(422, "Неизвестный тип пучка")
    extras = {r["code"] for r in conn.execute("SELECT code FROM uncertainty_settings WHERE modality = %s AND is_extra AND active",
                                              (modality,)).fetchall()}
    changed = 0
    for key in form.keys():
        if not key.startswith("u_"):
            continue
        code = key[2:]
        value = unc_number(form.get(key), "u, %")
        if code in extras:
            conn.execute("UPDATE uncertainty_settings SET u_pct = %s, updated_by = %s, updated_at = now() "
                         "WHERE modality = %s AND code = %s AND is_extra", (value, user["id"], modality, code))
            changed += 1
            continue
        default = unc_number(form.get("d_" + code), "u по умолчанию, %")
        if abs(value - default) < 1e-9:
            conn.execute("UPDATE uncertainty_settings SET active = false, updated_by = %s, updated_at = now() "
                         "WHERE modality = %s AND code = %s AND NOT is_extra AND active", (user["id"], modality, code))
        else:
            conn.execute("""INSERT INTO uncertainty_settings(modality, code, u_pct, updated_by) VALUES (%s, %s, %s, %s)
                            ON CONFLICT (modality, code) DO UPDATE SET u_pct = EXCLUDED.u_pct, active = true,
                            updated_by = EXCLUDED.updated_by, updated_at = now()""", (modality, code, value, user["id"]))
            changed += 1
    audit(conn, user["id"], "uncertainty_settings", "uncertainty", modality, {"changed": changed})
    return RedirectResponse(unc_back(form), status_code=303)


@app.post("/uncertainty/settings/reset")
async def unc_reset(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    modality = form.get("modality")
    if modality not in ("photon", "electron"):
        raise HTTPException(422, "Неизвестный тип пучка")
    conn.execute("UPDATE uncertainty_settings SET active = false, updated_by = %s, updated_at = now() "
                 "WHERE modality = %s AND NOT is_extra AND active", (user["id"], modality))
    audit(conn, user["id"], "uncertainty_reset", "uncertainty", modality)
    return RedirectResponse(unc_back(form), status_code=303)


@app.post("/uncertainty/extra")
async def unc_extra_add(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    modality, name = form.get("modality"), (form.get("name") or "").strip()
    stage = form.get("stage")
    if modality not in ("photon", "electron") or stage not in ("1", "2"):
        raise HTTPException(422, "Неизвестный тип пучка или этап")
    if len(name) < 3:
        raise HTTPException(422, "Укажите название строки (не короче 3 символов)")
    value = unc_number(form.get("u_new"), "u, %")
    dist = (form.get("dist") or "").strip()
    if dist and dist not in udist.DISTRIBUTIONS:
        raise HTTPException(422, "Неизвестное распределение")
    code = "x" + secrets.token_hex(4)
    conn.execute("""INSERT INTO uncertainty_settings(modality, code, is_extra, stage, name, u_pct, note, updated_by, dist, how)
                    VALUES (%s, %s, true, %s, %s, %s, NULLIF(%s, ''), %s, NULLIF(%s, ''), NULLIF(%s, ''))""",
                 (modality, code, int(stage), name, value, (form.get("note") or "").strip(), user["id"], dist,
                  (form.get("how") or "").strip()[:400]))
    audit(conn, user["id"], "uncertainty_extra_add", "uncertainty", code, {"name": name, "u": value, "dist": dist})
    return RedirectResponse(unc_back(form), status_code=303)


@app.post("/uncertainty/extra/delete")
async def unc_extra_delete(request: Request, user=Depends(require("physicist", "admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    row = conn.execute("UPDATE uncertainty_settings SET active = false, updated_by = %s, updated_at = now() "
                       "WHERE modality = %s AND code = %s AND is_extra AND active RETURNING code",
                       (user["id"], form.get("modality"), form.get("code"))).fetchone()
    if not row:
        raise HTTPException(404, "Строка не найдена")
    audit(conn, user["id"], "uncertainty_extra_remove", "uncertainty", row["code"])
    return RedirectResponse(unc_back(form), status_code=303)


@app.get("/uncertainty", response_class=HTMLResponse)
def uncertainty_page(request: Request, beam_id: str = "", chamber: str = "", q0: str = "", r50: str = "",
                     tolerance: str = "", observe: str = "", interval: str = "", window: str = "",
                     last_cal: str = "", user=Depends(current_user), conn=Depends(get_db)):
    beams = conn.execute("SELECT b.*, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id "
                         "ORDER BY l.name, b.modality, b.nominal_energy, b.fff").fetchall()
    for b in beams:
        b["label"] = ("γ " if b["modality"] == "photon" else "e⁻ ") + beam_label(b)
    ctx = dict(beams=beams, beam=None, budget=None, advice=None, shares=[], electron_chambers=[], form={})
    if not beam_id:
        return render(request, "uncertainty.html", user, **ctx)
    beam = next((b for b in beams if str(b["id"]) == beam_id), None)
    if not beam:
        raise HTTPException(404, "Пучок не найден")

    pts = trend_points(conn, beam)
    summary = spc.analyse(pts, periods=beam_periods(conn, beam["id"])[0])
    sigma_a = summary.sigma

    if beam["modality"] == "photon":
        budget = uncertainty.photon_budget(sigma_a)
    else:
        names = [c["name"] for c in el_core.load_tables()["chambers"]]
        last = conn.execute("""SELECT s.beam_quality, s.extra, ch.name AS chamber FROM measurement_sessions s
            JOIN calibrations cal ON cal.id = s.calibration_id JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
            JOIN chambers ch ON ch.id = cu.chamber_id
            WHERE s.beam_id = %s AND s.status = 'approved' ORDER BY s.measured_on DESC, s.id DESC LIMIT 1""",
                            (beam["id"],)).fetchone()
        chamber_name = chamber or (last["chamber"] if last and last["chamber"] in names else names[0])
        q0_co60 = (q0 == "co60") if q0 else (bool(last["extra"].get("form", {}).get("q0_is_co60")) if last else True)
        r50w = _opt_float(r50, float(last["extra"].get("r50w") or last["beam_quality"]) if last else 4.0,
                          "R50", 0.5, 12)
        info = next(c for c in el_core.load_tables()["chambers"] if c["name"] == chamber_name)
        budget = uncertainty.electron_budget(info["plane_parallel"], q0_co60, r50w, sigma_a)
        ctx.update(electron_chambers=names, form=dict(chamber=chamber_name, q0="co60" if q0_co60 else "electron",
                                                      r50=f"{r50w:g}", plane_parallel=info["plane_parallel"]))

    last_cal = _opt_date(last_cal)
    form = dict(ctx["form"], tolerance=_opt_float(tolerance, 2.0, "Допуск", 0.5, 10),
                observe=_opt_float(observe, 1.0, "Уровень наблюдения", 0.1, 10),
                interval=int(_opt_float(interval, 12, "Интервал, мес", 1, 60)),
                window=int(_opt_float(window, 12, "Окно, записей", 3, 200)), last_cal=last_cal.isoformat() if last_cal else "")
    advice = uncertainty.recalibration_advice(
        [(p.on, p.deviation_pct) for p in pts], sigma_a, tolerance=form["tolerance"], observe=form["observe"],
        interval_months=form["interval"], last_calibration=last_cal, window=form["window"],
        signals=bool(summary.points and (summary.points[-1].signal or summary.points[-1].cusum_signal)))
    budget = uncertainty.apply_settings(budget, *unc_settings(conn, beam["modality"]))
    shares = budget.contributions()
    ctx.update(can_edit_unc=user["role"] in ("physicist", "admin"), modality=beam["modality"], presets=ulit.PRESETS,
               literature=ulit.LITERATURE, lit_sources=ulit.SOURCES, lit_dist=ulit.LIT_DIST, preset_dist=ulit.PRESET_DIST,
               dist_names={k: v[0] for k, v in udist.DISTRIBUTIONS.items()}, dist_formulas=udist.FORMULAS, dist_rules=udist.SENSITIVITY_RULES, beam=beam, budget=budget, advice=advice, shares=shares, form=form, n_points=summary.n,
               plot={"names": [str(sym(s[0])) for s in shares][::-1], "share": [round(s[3], 2) for s in shares][::-1],
                     "u": [round(s[2], 3) for s in shares][::-1], "kinds": [s[1] for s in shares][::-1]})
    return render(request, "uncertainty.html", user, **ctx)

# ---------------------------------------------------------------- equipment
def form_text(form, name):
    """A text cell of a form, checked against the rule of its field (length, allowed signs); an error is a 422."""
    try:
        return fields.check_text(name, form.get(name))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def eq_back(form) -> str:
    """Where to return after a change on the equipment page (the tab and the selected linac), never outside /equipment."""
    back = (form.get("back") or "").strip()
    return back if back.startswith("/equipment") and "//" not in back else "/equipment"


def beam_readiness(b) -> dict:
    """What a beam still lacks to be used smoothly on the calculation sheet: hard (the sheet cannot be completed) and soft (convenience)."""
    hard, soft = [], []
    if b.get("zmax") is None:
        hard.append("zmax")
    if b.get("pdd_zref") is None:
        hard.append("PDD(zref)")
    if not (b.get("field_size") or "").strip():
        soft.append("размер поля")
    if b.get("ref_depth") is None:
        soft.append("референсная глубина")
    if b.get("dose_rate_mu") is None:
        soft.append("мощность дозы")
    if b.get("cal_mu") is None:
        soft.append("MU при калибровке")
    return {"hard": hard, "soft": soft, "state": "bad" if hard else "warn" if soft else "ok"}


REMINDER_MONTHS = 3                                  # a chamber calibration is reminded about this many months before it expires


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    year, month = d.year + m // 12, m % 12 + 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def calibration_state(c, today) -> dict:
    """Validity of a calibration: expired, soon (within the reminder period of 3 calendar months) or valid."""
    if not c.get("valid_until"):
        return {"state": "none", "days": None}
    days = (c["valid_until"] - today).days
    return {"state": "expired" if days < 0 else "soon" if c["valid_until"] <= add_months(today, REMINDER_MONTHS) else "ok", "days": days}


def calibration_reminders(conn, today) -> list[dict]:
    """The chambers whose newest calibration has expired or expires within 3 months (the banner on the list of measurements)."""
    rows = conn.execute("""SELECT ch.name AS chamber, cu.serial_no, cal.valid_until, cal.calibrated_on
        FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id JOIN chambers ch ON ch.id = cu.chamber_id
        ORDER BY ch.name, cu.serial_no, cal.calibrated_on DESC, cal.id DESC""").fetchall()
    newest = {}
    for r in rows:
        newest.setdefault((r["chamber"], r["serial_no"]), r)         # the first row of a unit is its newest calibration
    out = []
    for r in newest.values():
        st = calibration_state(r, today)
        if st["state"] in ("expired", "soon"):
            out.append({**r, **st})
    return sorted(out, key=lambda r: r["valid_until"])


@app.get("/equipment", response_class=HTMLResponse)
def equipment(request: Request, tab: str = "beams", linac: str = "", saved: str = "", user=Depends(current_user), conn=Depends(get_db)):
    tab = tab if tab in ("beams", "dosimeters", "reference") else "beams"
    today = date.today()
    linacs = conn.execute("""SELECT l.*, (SELECT count(*) FROM beams b WHERE b.linac_id = l.id) AS n_beams
                             FROM linacs l ORDER BY l.name""").fetchall()
    ctx = dict(tab=tab, linacs=linacs, today=today, q0_options=CAL_Q0, saved=saved if saved.isdigit() else "")
    if tab == "beams":
        current = next((l for l in linacs if str(l["id"]) == linac), linacs[0] if linacs else None)
        all_beams = conn.execute("SELECT b.*, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id WHERE b.linac_id = %s "
                                 "ORDER BY b.modality, b.nominal_energy, b.fff", (current["id"],)).fetchall() if current else []
        for b in all_beams:
            b["records"] = beam_usage(conn, b["id"])
            b["ready"] = beam_readiness(b)
        beams = [b for b in all_beams if not b["archived"]]
        archived_beams = [b for b in all_beams if b["archived"]]
        for l in linacs:
            l["incomplete"] = sum(1 for b in conn.execute("SELECT * FROM beams WHERE linac_id = %s", (l["id"],)).fetchall()
                                  if beam_readiness(b)["state"] == "bad")
        ctx.update(current=current, archived_beams=archived_beams, photon_beams=[b for b in beams if b["modality"] == "photon"],
                   electron_beams=[b for b in beams if b["modality"] == "electron"], beams=beams)
    elif tab == "dosimeters":
        cals = conn.execute("""SELECT cal.*, ch.name AS chamber, cu.serial_no, el.model AS el_model, el.serial_no AS el_sn
            FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
            JOIN chambers ch ON ch.id = cu.chamber_id LEFT JOIN electrometers el ON el.id = cal.electrometer_id
            ORDER BY ch.name, cu.serial_no, cal.calibrated_on DESC""").fetchall()
        units = {}
        for c in cals:
            c["used"] = conn.execute("SELECT count(*) AS n FROM measurement_sessions WHERE calibration_id = %s",
                                     (c["id"],)).fetchone()["n"]
            c["nd_warn"] = services.nd_w_warning(c["chamber"], c["nd_w"])
            c["state"] = calibration_state(c, today)
            units.setdefault((c["chamber"], c["serial_no"]), []).append(c)
        unit_rows = [dict(chamber=k[0], serial_no=k[1], cals=v, current=v[0], state=v[0]["state"]) for k, v in units.items()]
        electrometers = conn.execute("""SELECT el.*, (SELECT count(*) FROM calibrations c WHERE c.electrometer_id = el.id) AS n_cals
                                        FROM electrometers el ORDER BY el.model, el.serial_no""").fetchall()
        ctx.update(unit_rows=unit_rows, electrometers=electrometers,
                   chambers=conn.execute("SELECT id, name FROM chambers ORDER BY name").fetchall())
    else:
        refs = conn.execute("""SELECT r.*, b.modality, b.nominal_energy, b.fff, l.name AS linac, ch.name AS chamber, cu.serial_no,
                                      u.full_name AS who
            FROM beam_reference r JOIN beams b ON b.id = r.beam_id JOIN linacs l ON l.id = b.linac_id
            JOIN chamber_units cu ON cu.id = r.chamber_unit_id JOIN chambers ch ON ch.id = cu.chamber_id
            JOIN users u ON u.id = r.set_by ORDER BY l.name, b.modality, b.nominal_energy, b.fff, ch.name""").fetchall()
        for r in refs:
            r["label"] = ("γ " if r["modality"] == "photon" else "e⁻ ") + beam_label(r)
        ctx.update(refs=refs, ref_fields=REFERENCE_SAVED)
    return render(request, "equipment.html", user, **ctx)


@app.post("/equipment/reference/delete")
async def delete_reference(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    row = conn.execute("DELETE FROM beam_reference WHERE beam_id = %s AND chamber_unit_id = %s RETURNING beam_id",
                       (int_or_404(form.get("beam_id"), "Пучок"), int_or_404(form.get("chamber_unit_id"), "Камера"))).fetchone()
    if not row:
        raise HTTPException(404, "Опорные значения не найдены")
    audit(conn, user["id"], "delete_beam_reference", "beams", row["beam_id"], {"chamber_unit_id": form.get("chamber_unit_id")})
    return RedirectResponse(eq_back(form), status_code=303)


def beam_usage(conn, beam_id):
    """Records of a beam: all, the locked ones (approved, superseded, annulled: history) and the imported journal rows."""
    return conn.execute("""SELECT (SELECT count(*) FROM measurement_sessions WHERE beam_id = %s) AS sessions,
                                  (SELECT count(*) FROM measurement_sessions WHERE beam_id = %s AND status NOT IN ('draft', 'returned')) AS locked,
                                  (SELECT count(*) FROM legacy_journal WHERE beam_id = %s) AS legacy""",
                        (beam_id, beam_id, beam_id)).fetchone()


@app.post("/equipment/linac/{lid}/rename")
async def rename_linac(request: Request, lid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    name = form_text(form, "name")
    if not name:
        raise HTTPException(422, "Название аппарата не может быть пустым")
    lid = int_or_404(lid, "Аппарат")
    if conn.execute("SELECT 1 FROM linacs WHERE name = %s AND id <> %s", (name, lid)).fetchone():
        raise HTTPException(409, "Аппарат с таким названием уже есть")
    before = conn.execute("SELECT * FROM linacs WHERE id = %s", (lid,)).fetchone()
    row = conn.execute("""UPDATE linacs SET name = %s, site = NULLIF(%s, ''), model = NULLIF(%s, ''),
                           serial_no = NULLIF(%s, ''), city = NULLIF(%s, '') WHERE id = %s RETURNING id""",
                       (name, form_text(form, "site") or "", form_text(form, "model") or "",
                        form_text(form, "serial_no") or "", form_text(form, "city") or "", lid)).fetchone()
    if not row:
        raise HTTPException(404, "Аппарат не найден")
    after = conn.execute("SELECT * FROM linacs WHERE id = %s", (lid,)).fetchone()
    audit(conn, user["id"], "rename_linac", "linacs", lid, {"changes": auditlog.as_json(auditlog.diff(before or {}, after))})
    return RedirectResponse(eq_back(form), status_code=303)


@app.post("/equipment/linac/{lid}/delete")
async def delete_linac(request: Request, lid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    lid = int_or_404(lid, "Аппарат")
    n = conn.execute("SELECT count(*) AS n FROM beams WHERE linac_id = %s", (lid,)).fetchone()["n"]
    if n:
        raise HTTPException(409, f"У аппарата есть пучки ({n}). Сначала удалите пучки (без записей) "
                                 "или переименуйте аппарат вместо удаления")
    if not conn.execute("DELETE FROM linacs WHERE id = %s RETURNING id", (lid,)).fetchone():
        raise HTTPException(404, "Аппарат не найден")
    audit(conn, user["id"], "delete_linac", "linacs", lid)
    return RedirectResponse(eq_back(form), status_code=303)


@app.post("/equipment/beam/{bid}/delete")
async def delete_beam(request: Request, bid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    bid = int_or_404(bid, "Пучок")
    use = beam_usage(conn, bid)
    if use["sessions"] or use["legacy"]:
        raise HTTPException(409, f"У пучка есть данные: измерений {use['sessions']}, исторических записей {use['legacy']}. "
                                 "Отправьте пучок в архив; если все записи пучка черновики, его можно удалить вместе с ними")
    conn.execute("DELETE FROM spc_baseline WHERE beam_id = %s", (bid,))
    if not conn.execute("DELETE FROM beams WHERE id = %s RETURNING id", (bid,)).fetchone():
        raise HTTPException(404, "Пучок не найден")
    audit(conn, user["id"], "delete_beam", "beams", bid)
    return RedirectResponse(eq_back(form), status_code=303)


@app.post("/equipment/beam/{bid}/archive")
async def archive_beam(request: Request, bid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    """A beam entered by mistake (or no longer used) leaves the choices of a new measurement; its records stay."""
    form = await request.form()
    check_csrf(request, form)
    bid = int_or_404(bid, "Пучок")
    on = form.get("archived") != "0"
    row = conn.execute("""UPDATE beams SET archived = %s, archived_at = CASE WHEN %s THEN now() END,
                          archived_by = CASE WHEN %s THEN %s END WHERE id = %s RETURNING id""",
                       (on, on, on, user["id"], bid)).fetchone()
    if not row:
        raise HTTPException(404, "Пучок не найден")
    audit(conn, user["id"], "archive_beam" if on else "restore_beam", "beams", bid)
    return RedirectResponse(eq_back(form), status_code=303)


@app.post("/equipment/beam/{bid}/purge")
async def purge_beam(request: Request, bid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    """Delete a beam together with its drafts and returned records (never approved, superseded or annulled ones)."""
    form = await request.form()
    check_csrf(request, form)
    bid = int_or_404(bid, "Пучок")
    use = beam_usage(conn, bid)
    if use["locked"]:
        raise HTTPException(409, f"У пучка есть утверждённые, замещённые или аннулированные записи ({use['locked']}): это история, "
                                 "удалить их нельзя. Отправьте пучок в архив")
    if use["legacy"] and not form.get("with_legacy"):
        raise HTTPException(409, f"У пучка есть импортированные записи журнала ({use['legacy']}): отметьте их удаление или отправьте пучок в архив")
    try:
        dbops.delete_beam_with_drafts(conn, bid, user["id"], bool(form.get("with_legacy")))
    except dbops.MaintenanceError as e:
        raise HTTPException(409, str(e)) from None
    return RedirectResponse(eq_back(form), status_code=303)


@app.post("/equipment/calibration/{cid}/delete")
async def delete_calibration(request: Request, cid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    cid = int_or_404(cid, "Калибровка")
    used = conn.execute("SELECT count(*) AS n FROM measurement_sessions WHERE calibration_id = %s",
                        (cid,)).fetchone()["n"]
    if used:
        raise HTTPException(409, f"Калибровка используется в измерениях ({used}); удалить её нельзя")
    row = conn.execute("DELETE FROM calibrations WHERE id = %s RETURNING chamber_unit_id", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "Калибровка не найдена")
    conn.execute("""DELETE FROM chamber_units WHERE id = %s
                    AND NOT EXISTS (SELECT 1 FROM calibrations WHERE chamber_unit_id = %s)""",
                 (row["chamber_unit_id"], row["chamber_unit_id"]))
    audit(conn, user["id"], "delete_calibration", "calibrations", cid)
    return RedirectResponse(eq_back(form), status_code=303)


@app.post("/equipment/linac")
async def add_linac(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    name = form_text(form, "name")
    if not name:
        raise HTTPException(422, "Укажите название аппарата")
    conn.execute("""INSERT INTO linacs(name, site, model, serial_no, city)
                    VALUES (%s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, '')) ON CONFLICT (name) DO NOTHING""",
                 (name, form_text(form, "site") or "", form_text(form, "model") or "",
                  form_text(form, "serial_no") or "", form_text(form, "city") or ""))
    audit(conn, user["id"], "add_linac", "linacs", name)
    return RedirectResponse(eq_back(form), status_code=303)


@app.post("/equipment/beam")
async def add_beam(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    modality = form.get("modality")
    if modality not in ("photon", "electron"):
        raise HTTPException(422, "Неизвестный тип пучка")
    try:
        energy = services.num(form.get("energy"), "Энергия", lo=0.1, hi=50)
    except services.InputError as e:
        raise HTTPException(422, str(e)) from None
    conn.execute("""INSERT INTO beams(linac_id, modality, nominal_energy, fff) VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING""",
                 (int_or_404(form.get("linac_id"), "Аппарат"), modality, energy,
                  bool(form.get("fff")) and modality == "photon"))
    audit(conn, user["id"], "add_beam", "beams", None, {"modality": modality, "energy": energy})
    return RedirectResponse(eq_back(form), status_code=303)


CAL_Q0 = ("Co-60", "электронный пучок", "фотонный")


def _pol(form, prefix):
    text = ("+" if form.get(prefix + "_plus") else "") + ("−" if form.get(prefix + "_minus") else "")
    return text or None


def parse_calibration(form, conn):
    """Validated column values of a calibration from the equipment form (create and edit share it)."""
    def number(name, label, lo, hi, required=False):
        if name in fields.FIELDS:                     # the limits come from the table of fields (app/fields.py)
            lo, hi = fields.limits(name)
        try:
            return services.num(form.get(name), label, required=required, lo=lo, hi=hi)
        except services.InputError as e:
            raise HTTPException(422, str(e)) from None

    def day(name, label, required=False, past=False):
        text = (form.get(name) or "").strip()
        if not text:
            if required:
                raise HTTPException(422, f"Укажите: {label}")
            return None
        try:
            value = date.fromisoformat(text)
        except ValueError:
            raise HTTPException(422, f"«{label}»: дата в формате ГГГГ-ММ-ДД") from None
        if past and value > date.today():
            raise HTTPException(422, f"«{label}»: дата {value:%d.%m.%Y} позже сегодняшней")
        return value

    q0 = form.get("q0") or "Co-60"
    if q0 not in CAL_Q0:
        raise HTTPException(422, "Неизвестное качество калибровки Q0")
    separate = bool(form.get("kelec_separate"))
    k_elec = number("k_elec", "kelec", 0.5, 1.5)
    if separate and k_elec is None:
        raise HTTPException(422, "Электрометр калибруется отдельно: укажите kelec из свидетельства (например, ВНИИФТРИ)")
    r50_q0 = number("r50_q0", "R50 калибровочного пучка", 0.5, 12)
    if q0 == "электронный пучок" and r50_q0 is None:
        raise HTTPException(422, "Калибровка в электронном пучке: укажите его R50,w")
    el_model, el_sn = form_text(form, "el_model") or "", form_text(form, "el_sn") or ""
    electrometer_id = None
    if el_model or el_sn:
        if not (el_model and el_sn):
            raise HTTPException(422, "Укажите и модель, и серийный номер электрометра (или оставьте оба поля пустыми)")
        conn.execute("INSERT INTO electrometers(model, serial_no) VALUES (%s, %s) ON CONFLICT DO NOTHING", (el_model, el_sn))
        electrometer_id = conn.execute("SELECT id FROM electrometers WHERE model = %s AND serial_no = %s",
                                       (el_model, el_sn)).fetchone()["id"]

    def text(name):
        return form_text(form, name)
    return dict(
        nd_w=number("nd_w", "ND,w", 1e-6, 1000, required=True), k_elec=1.0 if k_elec is None else k_elec,
        kelec_separate=separate, lab=text("lab"), calibrated_on=day("calibrated_on", "дата калибровки", True, past=True),
        valid_until=day("valid_until", "действует до"), q0=q0, r50_q0=r50_q0,
        cal_depth=number("cal_depth", "калибровочная глубина", 0, 30), p0=number("p0", "P0", 80, 110),
        t0=number("t0", "T0", 0, 40), cal_rh=number("cal_rh", "влажность при калибровке", 0, 100),
        voltage_v=number("voltage_v", "V1 при калибровке", -3000, 3000), polarity_cal=_pol(form, "pol_cal"),
        cal_pol_corrected=bool(form.get("cal_pol_corrected")), polarity_user=_pol(form, "pol_user"),
        el_range=text("el_range"), kelec_lab=text("kelec_lab"), kelec_date=day("kelec_date", "дата калибровки электрометра", past=True),
        electrometer_id=electrometer_id)


@app.post("/equipment/calibration")
async def add_calibration(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    serial = form_text(form, "serial_no")
    if not serial:
        raise HTTPException(422, "Укажите серийный номер камеры")
    chamber_id = int_or_404(form.get("chamber_id"), "Камера")
    values = parse_calibration(form, conn)
    conn.execute("INSERT INTO chamber_units(chamber_id, serial_no) VALUES (%s, %s) ON CONFLICT DO NOTHING", (chamber_id, serial))
    unit = conn.execute("SELECT id FROM chamber_units WHERE chamber_id = %s AND serial_no = %s", (chamber_id, serial)).fetchone()
    cols = list(values)
    row = conn.execute(f"INSERT INTO calibrations(chamber_unit_id, {', '.join(cols)}) "
                       f"VALUES (%s, {', '.join(['%s'] * len(cols))}) RETURNING id",
                       [unit["id"]] + [values[c] for c in cols]).fetchone()
    audit(conn, user["id"], "add_calibration", "calibrations", row["id"])
    return RedirectResponse(eq_back(form), status_code=303)


def calibration_row(conn, cid):
    row = conn.execute("""SELECT cal.*, ch.name AS chamber, cu.serial_no, el.model AS el_model, el.serial_no AS el_sn
        FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id JOIN chambers ch ON ch.id = cu.chamber_id
        LEFT JOIN electrometers el ON el.id = cal.electrometer_id WHERE cal.id = %s""", (int_or_404(cid, "Калибровка"),)).fetchone()
    if not row:
        raise HTTPException(404, "Калибровка не найдена")
    row["used"] = conn.execute("SELECT count(*) AS n FROM measurement_sessions WHERE calibration_id = %s",
                               (row["id"],)).fetchone()["n"]
    return row


@app.get("/equipment/calibration/{cid}/edit", response_class=HTMLResponse)
def edit_calibration_form(request: Request, cid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    c = calibration_row(conn, cid)
    return render(request, "calibration_edit.html", user, c=c, q0_options=CAL_Q0)


@app.post("/equipment/calibration/{cid}/edit")
async def edit_calibration(request: Request, cid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    c = calibration_row(conn, cid)
    if c["used"]:
        raise HTTPException(409, f"Калибровка используется в измерениях ({c['used']}): менять её нельзя, чтобы не исказить "
                                 "протоколы. Добавьте новую калибровку (новый сертификат) с нужными значениями")
    values = parse_calibration(form, conn)
    conn.execute(f"UPDATE calibrations SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s",
                 list(values.values()) + [c["id"]])
    audit(conn, user["id"], "edit_calibration", "calibrations", c["id"], {"changes": auditlog.as_json(auditlog.diff(c, values))})
    return RedirectResponse(eq_back(form), status_code=303)


@app.post("/equipment/beam/{bid}/params")
async def beam_params(request: Request, bid: str, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)

    def number(name, *_unused):          # the limits come from the table of fields (app/fields.py)
        f = fields.FIELDS[name]
        try:
            return services.num(form.get(name), f.label, required=False, lo=f.lo, hi=f.hi)
        except services.InputError as e:
            raise HTTPException(422, str(e)) from None
    before = conn.execute("SELECT * FROM beams WHERE id = %s", (int_or_404(bid, "Пучок"),)).fetchone()
    expected = number("exp_cgy_mu")
    zref_in, depth_in = number("exp_zref"), number("ref_depth")                      # both are checked even if only one is used
    exp_depth = (zref_in or depth_in) if expected else None                         # the depth of the reference point is the reference depth of the beam
    row = conn.execute("""UPDATE beams SET dose_rate_mu = %s, field_size = NULLIF(%s, ''), phantom = NULLIF(%s, ''),
                          c_pl = %s, h_pl = %s, zmax = %s, window_material = NULLIF(%s, ''),
                          window_thickness = %s, pdd_zref = %s, tmr_zref = %s, exp_cgy_mu = %s, exp_zref = %s,
                          exp_source = NULLIF(%s, ''), cal_mu = %s, ref_depth = %s WHERE id = %s RETURNING id""",
                       (number("dose_rate", "мощность дозы", 1, 100000), form_text(form, "field_size") or "",
                        form_text(form, "phantom") or "", number("c_pl", "cpl", 0.5, 1.5), number("h_pl", "hpl", 0.5, 1.5),
                        number("zmax", "zmax", 0, 30), form_text(form, "window_material") or "",
                        number("window_thickness", "толщина окна", 0, 10), number("pdd_zref", "PDD(zref)", 30, 100),
                        number("tmr_zref", "TMR(zref)", 0.1, 1.5), expected,
                        exp_depth, form_text(form, "exp_source") or "",
                        number("cal_mu", "MU при калибровке", 1, 100000), number("ref_depth", "референсная глубина", 0.5, 30),
                        int_or_404(bid, "Пучок"))).fetchone()
    if not row:
        raise HTTPException(404, "Пучок не найден")
    after = conn.execute("SELECT * FROM beams WHERE id = %s", (row["id"],)).fetchone()
    audit(conn, user["id"], "beam_params", "beams", row["id"], {"changes": auditlog.as_json(auditlog.diff(before or {}, after))})
    back = eq_back(form)
    return RedirectResponse(f"{back}{'&' if '?' in back else '?'}saved={row['id']}#b{row['id']}", status_code=303)      # back to the same row


# ---------------------------------------------------------------- administration
@app.get("/admin/users", response_class=HTMLResponse)
def users_page(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    rows = conn.execute("SELECT id, login, full_name, role, is_active, created_at FROM users ORDER BY id").fetchall()
    return render(request, "admin_users.html", user, rows=rows, roles=ROLES, min_len=MIN_PASSWORD_LENGTH)


@app.post("/admin/users")
async def users_action(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    action = form.get("action")
    if action == "create":
        login_name, name = (form.get("login") or "").strip(), (form.get("full_name") or "").strip()
        role, password = form.get("role"), form.get("password") or ""
        if not login_name or not name or role not in ROLES:
            raise HTTPException(422, "Заполните логин, имя и роль")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise HTTPException(422, f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
        if conn.execute("SELECT 1 FROM users WHERE login = %s", (login_name,)).fetchone():
            raise HTTPException(409, "Такой логин уже есть")
        row = conn.execute("INSERT INTO users(login, full_name, role, password_hash) VALUES (%s, %s, %s, %s) "
                           "RETURNING id", (login_name, name, role, hash_password(password))).fetchone()
        audit(conn, user["id"], "create_user", "users", row["id"], {"role": role})
    else:
        target = conn.execute("SELECT * FROM users WHERE id = %s", (int_or_404(form.get("user_id"), "Пользователь"),)
                              ).fetchone()
        if not target:
            raise HTTPException(404, "Пользователь не найден")
        admins_left = conn.execute("SELECT count(*) AS n FROM users WHERE role = 'admin' AND is_active AND id <> %s",
                                   (target["id"],)).fetchone()["n"]
        if action == "set_role":
            role = form.get("role")
            if role not in ROLES:
                raise HTTPException(422, "Неизвестная роль")
            if target["role"] == "admin" and role != "admin" and admins_left == 0:
                raise HTTPException(409, "Нельзя снять права у последнего администратора")
            conn.execute("UPDATE users SET role = %s WHERE id = %s", (role, target["id"]))
            audit(conn, user["id"], "set_role", "users", target["id"], {"changes": {"role": [ROLE_LABELS.get(target["role"], target["role"]),
                                                                                         ROLE_LABELS.get(role, role)]}})
        elif action in ("deactivate", "activate"):
            if action == "deactivate" and target["role"] == "admin" and admins_left == 0:
                raise HTTPException(409, "Нельзя отключить последнего администратора")
            conn.execute("UPDATE users SET is_active = %s WHERE id = %s", (action == "activate", target["id"]))
            audit(conn, user["id"], action, "users", target["id"])
        elif action == "reset_password":
            password = form.get("password") or ""
            if len(password) < MIN_PASSWORD_LENGTH:
                raise HTTPException(422, f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
            conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(password), target["id"]))
            audit(conn, user["id"], "reset_password", "users", target["id"])
        else:
            raise HTTPException(422, "Неизвестное действие")
    return RedirectResponse("/admin/users", status_code=303)


def purge_counts(conn):
    return conn.execute("""SELECT (SELECT count(*) FROM measurement_sessions) AS sessions,
        (SELECT count(*) FROM results) AS results, (SELECT count(*) FROM legacy_journal) AS legacy,
        (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM audit_log) AS audit""").fetchone()


ENV_SETTINGS = {"TRS_LANG": "language", "BACKUP_HOUR": "backup_hour", "BACKUP_KEEP_DAYS": "backup_keep_days", "BACKUP_COPY_DIR": "backup_copy_dir"}


def settings_context(s: dict, **extra):
    return dict(s=s, lan_url=app_settings.lan_address(int(s["port"])), copy_dir=str(backups.copy_dir() or ""),
                env_overrides=[name for name in ENV_SETTINGS if os.environ.get(name)], **extra)


@app.get("/admin/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = "", user=Depends(require("admin"))):
    return render(request, "admin_settings.html", user, **settings_context(app_settings.load(), saved=saved == "1", errors=[]))


@app.post("/admin/settings", response_class=HTMLResponse)
async def settings_save(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    values, errors = app_settings.validate(dict(form))
    current = app_settings.load()
    if errors:
        return render(request, "admin_settings.html", user, status_code=422,
                      **settings_context({**current, **values, "lan": values["lan"]}, saved=False, errors=errors))
    new = {**current, **values}                                  # the folder of the second copy has its own form on the Backups page
    app_settings.save(new)
    changed = {k: new[k] for k in values if new[k] != current.get(k)}
    audit(conn, user["id"], "settings_changed", "settings", None, changed)
    return RedirectResponse("/admin/settings?saved=1", status_code=303)


@app.get("/admin/backups", response_class=HTMLResponse)
def backups_page(request: Request, requested: str = "", ext: str = "", extok: str = "", user=Depends(require("admin")),
                 conn=Depends(get_db)):
    return render(request, "admin_backups.html", user, backup=backups.latest(), files=backups.recent(), requested=bool(requested),
                  counts=purge_counts(conn), external=backups.external_status(), ext_message=ext[:300], ext_ok=extok == "1",
                  copy_dir=str(backups.copy_dir() or ""))


@app.post("/admin/backups/external")
async def backup_external(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    ok, message = backups.set_copy_dir(str(form.get("folder", "")))
    audit(conn, user["id"], "backup_copy_dir", "backups", None, {"folder": str(form.get("folder", ""))[:200], "ok": ok})
    from urllib.parse import quote
    return RedirectResponse(f"/admin/backups?extok={int(ok)}&ext={quote(message)}", status_code=303)


@app.post("/admin/backups/now")
async def backup_now(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    if not backups.request_now():
        raise HTTPException(503, "Не удалось отправить запрос службе копий. Сделайте копию вручную: пункт «Сделать резервную копию» в меню значка программы.")
    audit(conn, user["id"], "backup_requested", "backups", None)
    return RedirectResponse("/admin/backups?requested=1", status_code=303)


@app.get("/admin/purge", response_class=HTMLResponse)
def purge_page(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    return render(request, "admin_purge.html", user, counts=purge_counts(conn), backup=backups.latest(), scopes=PURGE_SCOPES,
                  confirmation=PURGE_CONFIRMATION, result=None, error=None)


@app.post("/admin/purge", response_class=HTMLResponse)
async def purge(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    form = await request.form()
    check_csrf(request, form)
    scope, reason = form.get("scope"), (form.get("reason") or "").strip()
    error = None
    if scope not in PURGE_SCOPES:
        error = "Выберите, что удалить"
    elif (form.get("confirmation") or "").strip() not in PURGE_CONFIRMATIONS:
        error = f"Для подтверждения введите слово {PURGE_CONFIRMATION} заглавными буквами"
    elif len(reason) < 5:
        error = "Укажите причину очистки (не короче 5 символов)"
    elif not verify_password(user["password_hash"], form.get("password") or ""):
        audit(conn, user["id"], "purge_denied", "purge", scope, {"why": "wrong password"})
        error = "Неверный пароль"
    result = None
    if not error:
        result = dbops.admin_purge(conn, scope, user["id"], reason)
    return render(request, "admin_purge.html", user, status_code=422 if error else 200, counts=purge_counts(conn), backup=backups.latest(),
                  scopes=PURGE_SCOPES, confirmation=PURGE_CONFIRMATION, result=result, error=error)


def audit_filters_context(conn, request: Request):
    f = auditlog.parse_filters(request.query_params)
    users = conn.execute("SELECT id, login FROM users ORDER BY login").fetchall()
    return f, users


@app.get("/admin/audit", response_class=HTMLResponse)
def audit_page(request: Request, page: int = 1, user=Depends(require("admin")), conn=Depends(get_db)):
    f, users = audit_filters_context(conn, request)
    rows, total = auditlog.search(conn, f, page)
    names = auditlog.describe(conn, rows)
    for r in rows:
        r["label"] = auditlog.label(r["action"])
        r["object"], r["url"] = names[(r["entity"], r["entity_id"])]
        r["lines"] = auditlog.details_lines(r.get("details"))
    pages = max(1, -(-total // auditlog.PAGE_SIZE))
    query = "&".join(f"{k}={v}" for k, v in request.query_params.items() if k != "page" and v)
    return render(request, "admin_audit.html", user, rows=rows, total=total, f=f, users=users, groups=auditlog.GROUPS,
                  actions=sorted(auditlog.ACTIONS.items(), key=lambda kv: kv[1][0]), page=min(max(page, 1), pages), pages=pages, query=query)


@app.get("/admin/audit.csv")
def audit_csv(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    f, _ = audit_filters_context(conn, request)
    rows, _total = auditlog.search(conn, f, limit=50000)
    audit(conn, user["id"], "audit_export", "system", None, {"rows": len(rows)})
    return Response(auditlog.to_csv(conn, rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="audit.csv"'})