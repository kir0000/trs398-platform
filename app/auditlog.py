"""The audit log made readable: the names of the actions, the objects they touched, the details with "was → became" for edits,
filters, pages and the CSV export. The records themselves are written by app.db.audit (append-only, see the triggers of the schema)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re

PAGE_SIZE = 100

# action code -> (what the administrator reads, group of the filter)
ACTIONS = {
    "login": ("Вход в программу", "Вход и пользователи"),
    "login_failed": ("Неудачная попытка входа", "Вход и пользователи"),
    "logout": ("Выход из программы", "Вход и пользователи"),
    "setup_admin": ("Создан первый администратор", "Вход и пользователи"),
    "bootstrap_admin": ("Создан администратор при установке", "Вход и пользователи"),
    "create_user": ("Создан пользователь", "Вход и пользователи"),
    "set_role": ("Изменена роль пользователя", "Вход и пользователи"),
    "deactivate": ("Пользователь отключён", "Вход и пользователи"),
    "activate": ("Пользователь включён", "Вход и пользователи"),
    "reset_password": ("Сброшен пароль пользователя", "Вход и пользователи"),
    "create": ("Создана запись измерения", "Измерения"),
    "edit": ("Изменена запись измерения", "Измерения"),
    "submit": ("Отправлено на проверку", "Измерения"),
    "approve": ("Запись утверждена", "Измерения"),
    "return": ("Запись возвращена на доработку", "Измерения"),
    "supersede": ("Запись заменена исправленной", "Измерения"),
    "void": ("Запись аннулирована", "Измерения"),
    "delete_draft": ("Удалён черновик", "Измерения"),
    "print": ("Открыта печатная форма протокола", "Измерения"),
    "pdf": ("Скачан PDF протокола", "Измерения"),
    "add_linac": ("Добавлен аппарат", "Оборудование"),
    "rename_linac": ("Аппарат переименован", "Оборудование"),
    "delete_linac": ("Аппарат удалён", "Оборудование"),
    "add_beam": ("Добавлен пучок", "Оборудование"),
    "beam_params": ("Изменены параметры пучка", "Оборудование"),
    "archive_beam": ("Пучок отправлен в архив", "Оборудование"),
    "restore_beam": ("Пучок возвращён из архива", "Оборудование"),
    "delete_beam": ("Пучок удалён", "Оборудование"),
    "delete_beam_with_drafts": ("Пучок удалён вместе с черновиками", "Оборудование"),
    "add_calibration": ("Добавлена калибровка камеры", "Оборудование"),
    "edit_calibration": ("Изменена калибровка камеры", "Оборудование"),
    "delete_calibration": ("Калибровка удалена", "Оборудование"),
    "beam_reference": ("Сохранены опорные значения пучка", "Оборудование"),
    "delete_beam_reference": ("Удалены опорные значения пучка", "Оборудование"),
    "set_baseline": ("Задан базовый период", "Тренды и неопределённость"),
    "trends_export": ("Выгружен тренд в файл", "Тренды и неопределённость"),
    "compare_export": ("Выгружено сравнение энергий в файл", "Тренды и неопределённость"),
    "delete_baseline": ("Базовый период удалён", "Тренды и неопределённость"),
    "uncertainty_settings": ("Изменены настройки бюджета неопределённости", "Тренды и неопределённость"),
    "uncertainty_reset": ("Настройки неопределённости сброшены", "Тренды и неопределённость"),
    "uncertainty_extra_add": ("Добавлена дополнительная составляющая неопределённости", "Тренды и неопределённость"),
    "uncertainty_extra_remove": ("Удалена дополнительная составляющая неопределённости", "Тренды и неопределённость"),
    "settings_changed": ("Изменены настройки программы", "Настройки и копии"),
    "access_denied": ("Отклонено обращение с неразрешённого адреса", "Вход и пользователи"),
    "backup_requested": ("Резервная копия по кнопке", "Настройки и копии"),
    "backup_auto": ("Автоматическая резервная копия", "Настройки и копии"),
    "backup_failed": ("Не удалась резервная копия", "Настройки и копии"),
    "backup_copy_dir": ("Изменена папка второй копии", "Настройки и копии"),
    "backup_copy_failed": ("Не удалась вторая копия", "Настройки и копии"),
    "restore": ("База восстановлена из копии", "Настройки и копии"),
    "app_start": ("Программа запущена", "Настройки и копии"),
    "audit_export": ("Выгружен журнал аудита в CSV", "Настройки и копии"),
    "seed_demo": ("Загружены демонстрационные данные", "Настройки и копии"),
    "remove_demo": ("Удалены демонстрационные данные", "Настройки и копии"),
    "remove_demo_beam": ("Демонстрационный пучок удалён (появились реальные данные)", "Настройки и копии"),
    "migration_applied": ("Обновлена структура базы", "Настройки и копии"),
    "purge": ("Очистка базы", "Очистка"),
    "purge_denied": ("Очистка отклонена", "Очистка"),
}
GROUPS = ["Вход и пользователи", "Измерения", "Оборудование", "Тренды и неопределённость", "Настройки и копии", "Очистка"]

ENTITIES = {"users": "Пользователь", "measurement": "Запись", "beams": "Пучок", "linacs": "Аппарат", "calibrations": "Калибровка",
            "spc_baseline": "Базовый период", "uncertainty": "Неопределённость", "settings": "Настройки", "backups": "Копии",
            "purge": "Очистка", "system": "Система", "seed": "Демонстрационные данные"}

LABELS = {
    "comment": "Комментарий", "reason": "Причина", "protocol_no": "Протокол №", "new_id": "Новая запись №", "restored_id": "Снова действует запись №",
    "modality": "Тип пучка", "energy": "Энергия", "role": "Роль", "name": "Название", "folder": "Папка", "ok": "Успешно", "why": "Причина отказа",
    "from": "С", "to": "По", "fields": "Поля", "chamber_unit_id": "Камера №", "changed": "Изменено параметров", "changes": "Изменения", "version": "Версия",
    "names": "Миграции", "file": "Файл", "error": "Ошибка", "sessions": "Записей", "results": "Результатов", "legacy": "Строк журнала",
    "drafts": "Черновиков", "scope": "Область", "unc": "Состав протокола", "u": "u, %", "dist": "Распределение", "status": "Статус",
    "beams": "Пучков", "linacs": "Аппаратов", "linac_fields": "Дополнены поля аппаратов (номера)", "beam_fields": "Дополнены поля пучков (номера)",
    "sessions_removed": "Удалено записей", "beam": "Пучок", "calibrations": "Калибровок", "units": "Камер", "electrometers": "Электрометров", "users": "Пользователей",
    "beam_id": "Пучок", "author_id": "Автор", "measured_on": "Дата измерения", "port": "Порт", "lan": "Доступ по сети", "language": "Язык",
    "backup_hour": "Час копии", "allowed_networks": "Разрешённые адреса", "session_hours": "Сеанс не дольше, часов",
    "session_idle_minutes": "Завершать сеанс после простоя, минут", "path": "Страница", "backup_keep_days": "Хранить копии, дней", "source": "Источник", "path": "Папка",
    # the columns that edits compare
    "mu": "MU", "pressure_kpa": "P, кПа", "temp_c": "T, °C", "humidity_pct": "Влажность, %", "v1": "V1, В", "v2": "V2, В",
    "m1_readings": "Показания M1", "m2_readings": "Показания M2", "m_plus_readings": "Показания M+", "m_minus_readings": "Показания M−",
    "beam_quality": "Качество пучка", "pdd_zref": "PDD(zref), %", "tmr_zref": "TMR(zref)", "note": "Примечание", "geometry": "Геометрия",
    "calibration_id": "Калибровка №", "dose_rate_mu": "Мощность дозы, MU/мин", "field_size": "Размер поля", "phantom": "Фантом",
    "c_pl": "cpl", "h_pl": "hpl", "zmax": "zmax, г/см²", "window_material": "Материал окна", "window_thickness": "Толщина окна, г/см²",
    "exp_cgy_mu": "Ожидаемая доза, сГр/MU", "exp_zref": "Глубина ожидаемой дозы, г/см²", "exp_source": "Источник ожидаемой дозы",
    "cal_mu": "MU при калибровке", "ref_depth": "Референсная глубина, г/см²", "nd_w": "ND,w", "q0": "Q0", "k_elec": "kelec",
    "format": "Формат", "rows": "Записей в ряду", "series": "Ряд", "voltage_v": "Напряжение калибровки, В", "polarity_calib": "Полярность при калибровке", "lab": "Лаборатория", "calibrated_on": "Дата калибровки",
    "valid_until": "Действует до", "kelec_separate": "kelec отдельно от камеры", "r50_q0": "R50 калибровочного пучка", "cal_depth": "Глубина калибровки",
    "p0": "P0, кПа", "t0": "T0, °C", "cal_rh": "Влажность при калибровке, %", "polarity_cal": "Полярность при калибровке",
    "cal_pol_corrected": "Поправка на полярность учтена", "polarity_user": "Полярность у пользователя", "el_range": "Диапазон электрометра",
    "kelec_lab": "kelec из свидетельства", "kelec_date": "Дата kelec", "electrometer_id": "Электрометр №",
}
# columns that say nothing to a reader when they change by themselves
SKIP = {"id", "extra", "status", "review_comment", "approved_by", "approved_at", "created_by", "created_at", "archived_at", "archived_by"}


# ------------------------------------------------------------------------------------------------ before / after
def _norm(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)) or (hasattr(v, "as_tuple")):
        return float(v)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if v == "":
        return None
    return v


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
ORDER = ["from", "to"]                                             # a period is read from the beginning to the end
def _roles() -> dict:
    from app.security import ROLE_LABELS
    return ROLE_LABELS


BOOLEAN_KEYS = {"fff", "archived", "kelec_separate", "cal_pol_corrected", "lan", "ok", "is_active"}


def text(v, key: str | None = None) -> str:
    """A value as the administrator reads it."""
    if key == "role" and isinstance(v, str) and v in _roles():
        return _roles()[v]
    if isinstance(v, bool) or (key in BOOLEAN_KEYS and v in (0, 1)):
        return "да" if v else "нет"
    v = _norm(v)
    if isinstance(v, str) and _ISO_DAY.fullmatch(v):               # dates as the program shows them everywhere: 31.10.2025
        return f"{v[8:10]}.{v[5:7]}.{v[0:4]}"
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, list):
        return ", ".join(text(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{LABELS.get(k, k)}: {text(x, k)}" for k, x in v.items())
    return str(v)


def diff(before: dict, after: dict, keys=None) -> dict:
    """{column: [was, became]} for the columns whose value differs (numbers by value, lists element by element)."""
    out = {}
    for k in (keys if keys is not None else after):
        if k in SKIP or k not in before:
            continue
        a, b = _norm(before.get(k)), _norm(after.get(k))
        if a != b:
            out[k] = [before.get(k), after.get(k)]
    return out


def as_json(changes: dict) -> dict:
    """The changes in a form that goes into the log (texts only)."""
    return {k: [text(a, k), text(b, k)] for k, (a, b) in changes.items()}


# ------------------------------------------------------------------------------------------------ reading
def label(action: str) -> str:
    return ACTIONS.get(action, (action, ""))[0]


FREE_TEXT = {"comment", "reason", "name", "note", "folder", "error", "file", "path"}          # typed by people or taken from the disk: never translated


def details_lines(details) -> list[tuple[str, str, bool]]:
    """The details of a record as lines (name, value, typed by a person)."""
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            return [("", details, True)]
    if not details:
        return []
    out = []
    for k, v in sorted(details.items(), key=lambda kv: ORDER.index(kv[0]) if kv[0] in ORDER else -1):
        name = LABELS.get(k, k)
        if k in ("changes", "changed") and isinstance(v, dict):
            for col, pair in v.items():
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    out.append((LABELS.get(col, col), f"{text(pair[0], col)} → {text(pair[1], col)}", col in FREE_TEXT))
                else:
                    out.append((LABELS.get(col, col), text(pair, col), col in FREE_TEXT))
        elif k in ("changed",) and isinstance(v, list):
            out.append((name, ", ".join(LABELS.get(x, str(x)) for x in v), False))
        elif k == "fields" and isinstance(v, list):
            out.append((name, ", ".join(LABELS.get(x, str(x)) for x in v), False))
        else:
            out.append((name, text(v, k), k in FREE_TEXT))
    return out


def describe(conn, rows) -> dict:
    """{(entity, entity_id): (text, url or None)} for the objects the records point to."""
    from app.common import beam_label                                # the same name of a beam as everywhere in the program

    def beam(bid):
        b = conn.execute("""SELECT b.*, l.name AS linac FROM beams b JOIN linacs l ON l.id = b.linac_id WHERE b.id = %s""", (bid,)).fetchone()
        return beam_label(b) if b else None                           # the label already starts with the linac

    out = {}
    for r in rows:
        key = (r["entity"], r["entity_id"])
        if key in out:
            continue
        ent, eid = key
        name, url = ENTITIES.get(ent, ent), None
        if eid is not None and str(eid).isdigit():
            n = int(eid)
            if ent == "measurement":
                s = conn.execute("SELECT protocol_no FROM measurement_sessions WHERE id = %s", (n,)).fetchone()
                detail = r.get("details") if isinstance(r.get("details"), dict) else {}
                num = (s or {}).get("protocol_no") or (detail or {}).get("protocol_no")
                name = f"Протокол № {num}" if num else f"Запись {n}"
                url = f"/measurements/{n}" if s else None
            elif ent in ("beams", "spc_baseline"):
                name = beam(n) or f"Пучок {n} (удалён)"
            elif ent == "linacs":
                row = conn.execute("SELECT name FROM linacs WHERE id = %s", (n,)).fetchone()
                name = f"Аппарат {row['name']}" if row else f"Аппарат {n} (удалён)"
            elif ent == "calibrations":
                row = conn.execute("""SELECT ch.name, cu.serial_no, cal.calibrated_on FROM calibrations cal
                    JOIN chamber_units cu ON cu.id = cal.chamber_unit_id JOIN chambers ch ON ch.id = cu.chamber_id WHERE cal.id = %s""", (n,)).fetchone()
                name = f"Калибровка {row['name']}, SN {row['serial_no']}, {row['calibrated_on']:%d.%m.%Y}" if row else f"Калибровка {n} (удалена)"
            elif ent == "users":
                row = conn.execute("SELECT login, full_name FROM users WHERE id = %s", (n,)).fetchone()
                name = f"Пользователь {row['login']} ({row['full_name']})" if row else f"Пользователь {n}"
            else:
                name = f"{name} {n}"
        elif eid:
            kinds = {"photon": "фотоны", "electron": "электроны"}
            name = f"{name}, {kinds[eid]}" if ent == "uncertainty" and eid in kinds else f"{name} {eid}"
        out[key] = (name, url)
    return out


# ------------------------------------------------------------------------------------------------ search
def parse_filters(params) -> dict:
    def day(name):
        try:
            return dt.date.fromisoformat(str(params.get(name, "")))
        except ValueError:
            return None
    user = str(params.get("user", ""))
    group = str(params.get("group", ""))
    action = str(params.get("action", ""))
    return {"user": int(user) if user.isdigit() else None, "group": group if group in GROUPS else "", "action": action if action in ACTIONS else "",
            "q": str(params.get("q", "")).strip()[:100], "from": day("from"), "to": day("to")}


def where(f: dict) -> tuple[str, list]:
    cond, args = [], []
    if f["user"] is not None:
        cond.append("a.user_id = %s")
        args.append(f["user"])
    if f["action"]:
        cond.append("a.action = %s")
        args.append(f["action"])
    elif f["group"]:
        codes = [c for c, (_, g) in ACTIONS.items() if g == f["group"]]
        cond.append(f"a.action IN ({', '.join(['%s'] * len(codes))})")
        args += codes
    if f["from"]:
        cond.append("date(a.at, 'localtime') >= %s")
        args.append(f["from"].isoformat())
    if f["to"]:
        cond.append("date(a.at, 'localtime') <= %s")
        args.append(f["to"].isoformat())
    if f["q"]:
        like = f"%{f['q']}%"
        names = [c for c, (lab, _) in ACTIONS.items() if f["q"].lower() in lab.lower()]
        part = "a.action LIKE %s OR a.entity LIKE %s OR a.entity_id LIKE %s OR a.details LIKE %s OR u.login LIKE %s OR a.ip LIKE %s"
        args += [like] * 6
        if names:
            part += f" OR a.action IN ({', '.join(['%s'] * len(names))})"
            args += names
        cond.append(f"({part})")
    return (" WHERE " + " AND ".join(cond)) if cond else "", args


def search(conn, f: dict, page: int = 1, limit: int | None = PAGE_SIZE):
    clause, args = where(f)
    base = f"FROM audit_log a LEFT JOIN users u ON u.id = a.user_id{clause}"
    total = conn.execute(f"SELECT count(*) AS n {base}", args).fetchone()["n"]
    sql = f"SELECT a.*, u.login {base} ORDER BY a.id DESC"
    if limit:
        sql += f" LIMIT {int(limit)} OFFSET {(max(page, 1) - 1) * int(limit)}"
    return conn.execute(sql, args).fetchall(), total


def to_csv(conn, rows) -> bytes:
    names = describe(conn, rows)
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Время", "Пользователь", "Адрес", "Действие", "Код действия", "Объект", "Подробности"])
    for r in rows:
        obj = names[(r["entity"], r["entity_id"])][0]
        det = "; ".join(f"{k}: {v}" for k, v, _free in details_lines(r.get("details")))
        w.writerow([r["at"].strftime("%d.%m.%Y %H:%M:%S"), r.get("login") or "", r.get("ip") or "", label(r["action"]), r["action"], obj, det])
    return ("﻿" + out.getvalue()).encode("utf-8")           # the BOM lets Excel read Cyrillic
