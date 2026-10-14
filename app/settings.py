"""The settings kept in <data>/settings.json (the page "Settings" of the administrator edits them):
port, access from the network, the allowed addresses, the lifetime of a session, language by default, the hour and the keeping period
of the backups, the folder of the second copy.
An environment variable of the same meaning (TRS_LANG, BACKUP_HOUR, BACKUP_KEEP_DAYS, BACKUP_COPY_DIR, TRS_ALLOWED_NETWORKS) overrides the file."""
from __future__ import annotations

import json
import socket
from pathlib import Path

from app import db

DEFAULTS = {"port": 8000, "lan": False, "language": "ru", "backup_hour": 2, "backup_keep_days": 30, "backup_copy_dir": "",
            "allowed_networks": "", "session_hours": 8, "session_idle_minutes": 0}
LIMITS = {"port": (1024, 65535), "backup_hour": (0, 23), "backup_keep_days": (1, 3650)}
OPTIONAL_LIMITS = {"session_hours": (1, 72), "session_idle_minutes": (0, 1440)}            # checked only when the form has them


def path() -> Path:
    return db.data_dir() / "settings.json"


def load() -> dict:
    try:
        return {**DEFAULTS, **json.loads(path().read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(s: dict) -> None:
    path().write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


def validate(form: dict) -> tuple[dict, list[str]]:
    """The values of the form as settings, and the list of mistakes (Russian texts for the page); nothing is saved here."""
    out, errors = {}, []
    names = {"port": "Порт", "backup_hour": "Час копии", "backup_keep_days": "Срок хранения копий"}
    for key, (low, high) in LIMITS.items():
        raw = str(form.get(key, "")).strip()
        try:
            value = int(raw)
        except ValueError:
            errors.append(f"{names[key]}: нужно целое число.")
            continue
        if not low <= value <= high:
            errors.append(f"{names[key]}: от {low} до {high}.")
            continue
        out[key] = value
    session_names = {"session_hours": "Сеанс не дольше, часов", "session_idle_minutes": "Простой до завершения сеанса, минут"}
    for key, (low, high) in OPTIONAL_LIMITS.items():
        if key not in form:
            continue
        try:
            value = int(str(form.get(key, "")).strip())
        except ValueError:
            errors.append(f"{session_names[key]}: нужно целое число.")
            continue
        if not low <= value <= high:
            errors.append(f"{session_names[key]}: от {low} до {high}.")
            continue
        out[key] = value
    if "allowed_networks" in form:
        from app import netaccess
        networks, bad = netaccess.parse(str(form.get("allowed_networks", "")))
        if bad:
            errors.append("Разрешённые адреса: не адрес или сеть: " + ", ".join(bad[:5]) + ". Примеры: 192.168.1.0/24, 10.0.0.15.")
        else:
            out["allowed_networks"] = ", ".join(str(n.network_address) if n.prefixlen == n.max_prefixlen else str(n) for n in networks)
    out["lan"] = str(form.get("lan", "")).lower() in ("1", "on", "true", "yes")
    language = str(form.get("language", "ru")).strip().lower()
    if language not in ("ru", "en"):
        errors.append("Язык: русский или английский.")
    out["language"] = language if language in ("ru", "en") else "ru"
    return out, errors


def lan_address(port: int) -> str:
    """The address the other computers of the network can use (the first address of this computer in the network)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return f"http://{s.getsockname()[0]}:{port}"
    except OSError:
        return f"http://{socket.gethostname()}:{port}"
