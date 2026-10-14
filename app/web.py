"""The common parts of the web side: templates and filters, the user of the request, roles, the CSRF token, the language, render."""
import hmac
import os
import secrets
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup as _Markup

from app import fields, i18n
from app.db import get_db
from app.notation import sym, sym_plain
from app.security import ROLE_LABELS, LoginThrottle, can_create, can_review

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


templates.env.globals.update(fa=lambda name: _Markup(fields.attrs(name)), fdatalists=lambda: _Markup(fields.datalists()))
throttle = LoginThrottle()


STATUS_LABELS = {"draft": "черновик", "submitted": "на проверке", "approved": "утверждено",
                 "returned": "возвращено", "superseded": "заменено", "voided": "аннулировано"}


class NotAuthenticated(Exception):
    pass


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


def int_or_404(value, what="Запись"):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(404, f"{what} не найдена") from None


# ---------------------------------------------------------------- auth
def has_users(conn) -> bool:
    """Real accounts exist (locked demonstration accounts, whose hash starts with "!", do not count)."""
    return conn.execute("SELECT count(*) AS n FROM users WHERE password_hash NOT LIKE '!%'").fetchone()["n"] > 0


def app_version() -> str:
    """The version of the program: from the image (TRS_VERSION), else from the file VERSION, else dev."""
    v = os.environ.get("TRS_VERSION", "")
    if not v or v == "dev":
        path = BASE.parent / "VERSION"
        v = path.read_text(encoding="utf-8").strip() + "+dev" if path.exists() else "dev"
    return v
