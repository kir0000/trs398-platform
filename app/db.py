import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


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
