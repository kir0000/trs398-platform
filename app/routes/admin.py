"""Administration: users, settings, backups, clearing the database, the audit log."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import netaccess, auditlog, backups, dbops, restore
from app import settings as app_settings
from app.db import audit, get_db
from app.security import MIN_PASSWORD_LENGTH, ROLE_LABELS, ROLES, hash_password, verify_password
from app.web import check_csrf, form_data, int_or_404, render, require

router = APIRouter()


PURGE_CONFIRMATION = "УДАЛИТЬ"
PURGE_CONFIRMATIONS = ("УДАЛИТЬ", "DELETE")      # the word the page shows depends on the language; either is accepted


PURGE_SCOPES = {"measurements": "Измерения и результаты", "legacy": "Исторические журналы (импорт)",
                "all": "Всё: измерения, результаты и исторические журналы"}


# ---------------------------------------------------------------- administration
@router.get("/admin/users", response_class=HTMLResponse)
def users_page(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    rows = conn.execute("SELECT id, login, full_name, role, is_active, created_at FROM users ORDER BY id").fetchall()
    return render(request, "admin_users.html", user, rows=rows, roles=ROLES, min_len=MIN_PASSWORD_LENGTH)


@router.post("/admin/users")
def users_action(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
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


ENV_SETTINGS = {"TRS_LANG": "language", "BACKUP_HOUR": "backup_hour", "BACKUP_KEEP_DAYS": "backup_keep_days", "BACKUP_COPY_DIR": "backup_copy_dir",
                "TRS_ALLOWED_NETWORKS": "allowed_networks"}


def settings_context(s: dict, **extra):
    return dict(s=s, lan_url=app_settings.lan_address(int(s["port"])), copy_dir=str(backups.copy_dir() or ""),
                env_overrides=[name for name in ENV_SETTINGS if os.environ.get(name)], **extra)


@router.get("/admin/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = "", user=Depends(require("admin"))):
    return render(request, "admin_settings.html", user, **settings_context(app_settings.load(), saved=saved == "1", errors=[]))


@router.post("/admin/settings", response_class=HTMLResponse)
def settings_save(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    values, errors = app_settings.validate(dict(form))
    current = app_settings.load()
    if not errors and values.get("allowed_networks"):
        host = request.client.host if request.client else None
        if not netaccess.is_allowed(host, netaccess.parse(values["allowed_networks"])[0]):       # the administrator would lock out the others (and himself)
            errors.append(f"Ваш адрес {host} не входит в список разрешённых. Добавьте его (или сеть, в которой он находится), иначе вы потеряете доступ с этого компьютера.")
    if errors:
        return render(request, "admin_settings.html", user, status_code=422,
                      **settings_context({**current, **values, "lan": values["lan"], "allowed_networks": str(form.get("allowed_networks", current["allowed_networks"]))},
                                         saved=False, errors=errors))
    new = {**current, **values}                                  # the folder of the second copy has its own form on the Backups page
    app_settings.save(new)
    changed = {k: new[k] for k in values if new[k] != current.get(k)}
    audit(conn, user["id"], "settings_changed", "settings", None, changed)
    return RedirectResponse("/admin/settings?saved=1", status_code=303)


@router.get("/admin/backups", response_class=HTMLResponse)
def backups_page(request: Request, requested: str = "", ext: str = "", extok: str = "", user=Depends(require("admin")),
                 conn=Depends(get_db)):
    return render(request, "admin_backups.html", user, backup=backups.latest(), files=backups.recent(), requested=bool(requested),
                  counts=purge_counts(conn), external=backups.external_status(), ext_message=ext[:300], ext_ok=extok == "1",
                  copy_dir=str(backups.copy_dir() or ""))


RESTORE_WORD = "ВОССТАНОВИТЬ"


@router.get("/admin/backups/restore", response_class=HTMLResponse)
def restore_page(request: Request, name: str = "", user=Depends(require("admin"))):
    try:
        info = restore.preview(name)
    except restore.RestoreError as e:
        raise HTTPException(404, str(e))
    return render(request, "admin_restore.html", user, info=info, word=RESTORE_WORD, error=None, result=None, form={})


@router.post("/admin/backups/restore", response_class=HTMLResponse)
def restore_run(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    """Restore from a copy: a reason, the password and a word; the copy is checked and a safety copy of the current database is made first."""
    check_csrf(request, form)
    name, reason = str(form.get("name", "")), (form.get("reason") or "").strip()
    error = result = None
    if (form.get("confirmation") or "").strip().upper() != RESTORE_WORD:
        error = f"Для подтверждения введите слово {RESTORE_WORD} заглавными буквами"
    elif not verify_password(user["password_hash"], form.get("password") or ""):
        audit(conn, user["id"], "restore_denied", "backups", None, {"file": name[:80], "why": "wrong password"})
        error = "Неверный пароль"
    login = user["login"]
    if not error:
        conn.commit()                                      # nothing of this request may stay open while the database is replaced
        try:
            result = restore.perform(login, name, reason)
        except restore.RestoreError as e:
            error = str(e)
    try:
        info = restore.preview(name)
    except restore.RestoreError as e:
        raise HTTPException(404, str(e))
    return render(request, "admin_restore.html", user, status_code=422 if error else 200, info=info, word=RESTORE_WORD, error=error, result=result,
                  form={"reason": reason})


@router.post("/admin/backups/external")
def backup_external(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    ok, message = backups.set_copy_dir(str(form.get("folder", "")))
    audit(conn, user["id"], "backup_copy_dir", "backups", None, {"folder": str(form.get("folder", ""))[:200], "ok": ok})
    from urllib.parse import quote
    return RedirectResponse(f"/admin/backups?extok={int(ok)}&ext={quote(message)}", status_code=303)


@router.post("/admin/backups/now")
def backup_now(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    check_csrf(request, form)
    if not backups.request_now():
        raise HTTPException(503, "Не удалось отправить запрос службе копий. Сделайте копию вручную: пункт «Сделать резервную копию» в меню значка программы.")
    audit(conn, user["id"], "backup_requested", "backups", None)
    return RedirectResponse("/admin/backups?requested=1", status_code=303)


@router.get("/admin/purge", response_class=HTMLResponse)
def purge_page(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    return render(request, "admin_purge.html", user, counts=purge_counts(conn), backup=backups.latest(), scopes=PURGE_SCOPES,
                  confirmation=PURGE_CONFIRMATION, result=None, error=None)


@router.post("/admin/purge", response_class=HTMLResponse)
def purge(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
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


AUDIT_CLEAR_WORDS = ("ОЧИСТИТЬ", "CLEAR")                      # the word the page shows depends on the language; either is accepted


def audit_clear_context(conn, **extra):
    row = conn.execute("SELECT count(*) AS n, min(at) AS first_at, max(at) AS last_at FROM audit_log").fetchone()
    return dict(total=row["n"], first=row["first_at"], last=row["last_at"], backup=backups.latest(), word=AUDIT_CLEAR_WORDS[0],
                archive_dir=str(backups.backup_dir() / "audit_archive"), result=None, error=None, **extra)


@router.get("/admin/audit/clear", response_class=HTMLResponse)
def audit_clear_page(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    return render(request, "admin_audit_clear.html", user, **audit_clear_context(conn, days="90"))


@router.post("/admin/audit/clear", response_class=HTMLResponse)
def audit_clear(request: Request, user=Depends(require("admin")), conn=Depends(get_db), form=Depends(form_data)):
    """The controlled clearing of the audit log: a reason, the password and a word; the archive and a safety copy are made first."""
    check_csrf(request, form)
    mode, reason = form.get("mode"), (form.get("reason") or "").strip()
    days_text = (form.get("days") or "").strip()
    error = None
    days = 0
    if mode not in ("older", "all"):
        error = "Выберите, что удалить"
    elif mode == "older" and not (days_text.isdigit() and 1 <= int(days_text) <= 3650):
        error = "Сколько дней оставить: целое число от 1 до 3650"
    elif (form.get("confirmation") or "").strip().upper() not in AUDIT_CLEAR_WORDS:
        error = f"Для подтверждения введите слово {AUDIT_CLEAR_WORDS[0]} заглавными буквами"
    elif len(reason) < 5:
        error = "Укажите причину очистки (не короче 5 символов)"
    elif not verify_password(user["password_hash"], form.get("password") or ""):
        audit(conn, user["id"], "audit_prune_denied", "audit", None, {"why": "wrong password"})
        error = "Неверный пароль"
    result = None
    if not error:
        days = int(days_text) if mode == "older" else 0
        try:
            result = dbops.prune_audit(conn, user["id"], days, reason, backups.backup_dir() / "audit_archive", backups.backup_dir() / "keep")
        except dbops.MaintenanceError as e:
            error = {"there are no records older than that": "Записей старше этого срока нет, удалять нечего",
                     "the audit log is empty": "Журнал пуст"}.get(str(e), str(e))
    return render(request, "admin_audit_clear.html", user, status_code=422 if error else 200,
                  **{**audit_clear_context(conn, days=days_text or "90"), "result": result, "error": error})


def audit_filters_context(conn, request: Request):
    f = auditlog.parse_filters(request.query_params)
    users = conn.execute("SELECT id, login FROM users ORDER BY login").fetchall()
    return f, users


@router.get("/admin/audit", response_class=HTMLResponse)
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


@router.get("/admin/audit.csv")
def audit_csv(request: Request, user=Depends(require("admin")), conn=Depends(get_db)):
    f, _ = audit_filters_context(conn, request)
    rows, _total = auditlog.search(conn, f, limit=50000)
    audit(conn, user["id"], "audit_export", "system", None, {"rows": len(rows)})
    return Response(auditlog.to_csv(conn, rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="audit.csv"'})
