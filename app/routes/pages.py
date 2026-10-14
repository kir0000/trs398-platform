"""Sign-in, first start, language, help, About and the check of health."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import applog, backups, i18n, updates
from app.db import audit, connect, data_dir, db_path, get_db
from app.security import MIN_PASSWORD_LENGTH, hash_password, verify_password
from app.web import BASE, app_version, check_csrf, current_lang, current_user, has_users, render, throttle

router = APIRouter()


@router.get("/lang/{code}")
def set_language(request: Request, code: str, next: str = "/"):
    """Switch the interface language (remembered in the session and in a cookie for a year)."""
    if code not in i18n.LANGS:
        raise HTTPException(404, "Неизвестный язык")
    request.session["lang"] = code
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie("lang", code, max_age=365 * 86400, samesite="lax")
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, created: str = "", conn=Depends(get_db)):
    if not has_users(conn):
        return RedirectResponse("/setup", status_code=303)             # first run: create the administrator
    return render(request, "login.html", created=bool(created))


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, conn=Depends(get_db)):
    if has_users(conn):
        return RedirectResponse("/login", status_code=303)
    return render(request, "setup.html", error=None, form={})


@router.post("/setup", response_class=HTMLResponse)
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


@router.post("/login")
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


@router.post("/logout")
async def logout(request: Request):
    form = await request.form()
    check_csrf(request, form)
    uid = request.session.get("uid")
    if uid:
        system_event_for_user(uid, "logout", "users", uid)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/")
def index(_user=Depends(current_user)):
    return RedirectResponse("/measurements", status_code=303)


@router.get("/help", response_class=HTMLResponse)
def help_page(request: Request, user=Depends(current_user)):
    """The user guide (docs/USER_GUIDE.md) inside the application: one source for the repository and for the people at work."""
    import markdown
    path = BASE.parent / "docs" / ("USER_GUIDE.en.md" if current_lang(request) == "en" else "USER_GUIDE.md")
    text = path.read_text(encoding="utf-8") if path.exists() else "Руководство не найдено."
    html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    return render(request, "help.html", user, content=html)


def about_context(**extra):
    path = db_path()
    return dict(version=app_version(), data_dir=str(data_dir()), db_file=str(path), log_file=str(applog.log_path()),
                db_mb=round(path.stat().st_size / 1048576, 1) if path.exists() else 0, backup=backups.latest(),
                external=backups.external_status(), **extra)


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request, user=Depends(current_user)):
    return render(request, "about.html", user, **about_context(update=None))


@router.post("/about/check", response_class=HTMLResponse)
async def about_check(request: Request, user=Depends(current_user)):
    """The only place where the program talks to the internet, and only after this button."""
    form = await request.form()
    check_csrf(request, form)
    return render(request, "about.html", user, **about_context(update=updates.check(app_version())))


@router.get("/healthz")
def healthz():
    return {"status": "ok", "version": app_version()}
