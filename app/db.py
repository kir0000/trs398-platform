"""The database of the program: one SQLite file (WAL mode).

The thin wrapper keeps the style of the code written for PostgreSQL: `%s` placeholders, rows as dictionaries, RETURNING.
Dates, times, booleans, JSON documents and arrays of readings are stored as text/ints and come back as Python objects
(by the name of the column, see _convert), so the rest of the program does not know what the file contains.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import sqlite3
from decimal import Decimal
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def data_dir() -> Path:
    """Where the data live: TRS_DATA, else a folder `data` next to the program."""
    p = Path(os.environ.get("TRS_DATA") or Path(__file__).resolve().parent.parent / "data")
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return Path(os.environ["TRS_DB"]) if os.environ.get("TRS_DB") else data_dir() / "trs398.db"


class Jsonb:
    """A document stored as JSON text (the name is kept from the PostgreSQL edition)."""
    def __init__(self, obj):
        self.obj = obj


sqlite3.register_adapter(Jsonb, lambda j: json.dumps(j.obj, ensure_ascii=False))
sqlite3.register_adapter(list, lambda v: json.dumps(v))                       # arrays of readings
sqlite3.register_adapter(dict, lambda v: json.dumps(v, ensure_ascii=False))
sqlite3.register_adapter(Decimal, float)
sqlite3.register_adapter(dt.date, lambda d: d.isoformat())
sqlite3.register_adapter(dt.datetime, lambda d: (d.astimezone(dt.timezone.utc).replace(tzinfo=None) if d.tzinfo else d).isoformat(sep=" ", timespec="seconds"))

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}")
BOOLEANS = {"is_active", "fff", "archived", "is_demo", "active", "is_extra", "kelec_separate", "cal_pol_corrected"}
JSON_COLUMNS = {"extra", "details", "data"}


def _is_date_name(name: str) -> bool:
    return name.endswith("_on") or name.endswith("_date") or name in ("valid_until", "from_date", "to_date")


def _is_stamp_name(name: str) -> bool:
    return name.endswith("_at") or name == "at"


def _convert(name: str, value):
    if value is None:
        return None
    if isinstance(value, str):
        if _is_date_name(name) and _DATE.match(value):
            return dt.date.fromisoformat(value)
        if _is_stamp_name(name) and _STAMP.match(value):         # stored in UTC, shown in local time like the timestamptz of PostgreSQL
            return dt.datetime.fromisoformat(value.replace("T", " ")[:19]).replace(tzinfo=dt.timezone.utc).astimezone()
        if name in JSON_COLUMNS or name.endswith("_readings"):
            try:
                return json.loads(value)
            except ValueError:
                return value
    elif name in BOOLEANS and isinstance(value, int):
        return bool(value)
    return value


def _dict_row(cursor, row):
    return {d[0]: _convert(d[0], v) for d, v in zip(cursor.description, row)}


_WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")


def translate(sql: str) -> str:
    """The SQL of the code written for PostgreSQL in the dialect of SQLite: placeholders, now(), IS NOT DISTINCT FROM."""
    sql = sql.replace("%%", "\x00").replace("%s", "?").replace("\x00", "%")
    sql = re.sub(r"\bnow\(\)", "CURRENT_TIMESTAMP", sql, flags=re.I)
    return re.sub(r"\bIS NOT DISTINCT FROM\b", "IS", sql, flags=re.I)


class Connection(sqlite3.Connection):
    """A connection that begins a write transaction (BEGIN IMMEDIATE) at the first change, so concurrent writers wait instead of failing."""

    def execute(self, sql, params=()):
        sql = translate(sql)
        if not self.in_transaction and sql.lstrip()[:7].upper().startswith(_WRITES):
            super().execute("BEGIN IMMEDIATE")
        return super().execute(sql, tuple(params))

    def __exit__(self, exc_type, exc, tb):                       # `with connect() as conn`: commit or roll back, then close
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


def connect(path: str | os.PathLike | None = None) -> Connection:
    conn = sqlite3.connect(str(path or db_path()), factory=Connection, isolation_level=None, check_same_thread=False, timeout=15)
    conn.row_factory = _dict_row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def pending(conn: Connection) -> list[str]:
    """The migrations this database has not seen yet (nothing is changed)."""
    has = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'").fetchone()
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()} if has else set()
    return [p.name for p in sorted(MIGRATIONS.glob("*.sql")) if p.name not in done]


def has_data(conn: Connection) -> bool:
    """True if this is not a new empty database (there is at least one user)."""
    has = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
    return bool(has and conn.execute("SELECT 1 FROM users LIMIT 1").fetchone())


def migrate(conn: Connection) -> list[str]:
    """Apply the migrations that this database has not seen yet (app/migrations/NNN_name.sql, in order). Returns their names."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        conn.executescript("BEGIN;\n" + path.read_text(encoding="utf-8") + "\nINSERT INTO schema_migrations(name) VALUES ('" + path.name + "');\nCOMMIT;")
        applied.append(path.name)
    return applied


def session_secret() -> str:
    """The key that signs the sessions: SESSION_SECRET, else a random one kept in the data folder (made at the first start)."""
    env = os.environ.get("SESSION_SECRET")
    if env:
        return env
    path = data_dir() / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def get_db():
    """FastAPI dependency: one connection per request, committed on success, rolled back on error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def audit(conn, user_id, action, entity, entity_id=None, details=None):
    conn.execute(
        "INSERT INTO audit_log(user_id, action, entity, entity_id, details) VALUES (%s, %s, %s, %s, %s)",
        (user_id, action, entity, None if entity_id is None else str(entity_id), Jsonb(details or {})),
    )
