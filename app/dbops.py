"""Maintenance operations that remove history (the SECURITY DEFINER functions of the PostgreSQL edition).

Each one checks who acts, does its work in the caller's transaction and writes the audit record itself.
They raise MaintenanceError with a message; the guard triggers of the schema stay in force for everything else.
"""
from __future__ import annotations

from app.db import Jsonb


class MaintenanceError(Exception):
    pass


def _flag(conn, on: bool) -> None:
    if on:
        conn.execute("INSERT OR IGNORE INTO _maintenance(k) VALUES ('purge')")
    else:
        conn.execute("DELETE FROM _maintenance WHERE k = 'purge'")


def delete_draft(conn, session_id: int, actor: int) -> str:
    """A draft or a returned record is deleted (by its author or an admin); the protocol number is not reused. Returns the number."""
    a = conn.execute("SELECT * FROM users WHERE id = %s AND is_active", (actor,)).fetchone()
    if not a:
        raise MaintenanceError("unknown or inactive user")
    s = conn.execute("SELECT * FROM measurement_sessions WHERE id = %s", (session_id,)).fetchone()
    if not s:
        raise MaintenanceError("record not found")
    if s["status"] not in ("draft", "returned"):
        raise MaintenanceError("only a draft or a returned record can be deleted")
    if s["created_by"] != actor and a["role"] != "admin":
        raise MaintenanceError("only the author or an admin can delete a record")
    conn.execute("DELETE FROM results WHERE session_id = %s", (session_id,))
    conn.execute("DELETE FROM measurement_sessions WHERE id = %s", (session_id,))
    conn.execute("INSERT INTO audit_log(user_id, action, entity, entity_id, details) VALUES (%s, 'delete_draft', 'measurement', %s, %s)",
                 (actor, str(session_id), Jsonb({"protocol_no": s["protocol_no"], "status": s["status"], "beam_id": s["beam_id"],
                                                 "measured_on": s["measured_on"].isoformat() if s["measured_on"] else None,
                                                 "author_id": s["created_by"]})))
    return s["protocol_no"]


def delete_beam_with_drafts(conn, beam_id: int, actor: int, with_legacy: bool = False) -> dict:
    """A beam is deleted together with its drafts and returned records; approved, superseded and annulled records block it."""
    if not conn.execute("SELECT 1 FROM users WHERE id = %s AND role = 'admin' AND is_active", (actor,)).fetchone():
        raise MaintenanceError("only an active admin may delete a beam")
    if not conn.execute("SELECT 1 FROM beams WHERE id = %s", (beam_id,)).fetchone():
        raise MaintenanceError("beam not found")
    row = conn.execute("""SELECT count(*) AS n, coalesce(sum(CASE WHEN status NOT IN ('draft', 'returned') THEN 1 ELSE 0 END), 0) AS locked
                          FROM measurement_sessions WHERE beam_id = %s""", (beam_id,)).fetchone()
    if row["locked"]:
        raise MaintenanceError("the beam has approved, superseded or annulled records: archive it instead")
    n_legacy = conn.execute("SELECT count(*) AS n FROM legacy_journal WHERE beam_id = %s", (beam_id,)).fetchone()["n"]
    if n_legacy and not with_legacy:
        raise MaintenanceError("the beam has imported journal rows: confirm their deletion")
    _flag(conn, True)                                  # the imported rows may go only inside a maintenance function
    try:
        conn.execute("DELETE FROM results WHERE session_id IN (SELECT id FROM measurement_sessions WHERE beam_id = %s)", (beam_id,))
        conn.execute("DELETE FROM measurement_sessions WHERE beam_id = %s", (beam_id,))
        conn.execute("DELETE FROM legacy_journal WHERE beam_id = %s", (beam_id,))
    finally:
        _flag(conn, False)
    conn.execute("DELETE FROM spc_baseline WHERE beam_id = %s", (beam_id,))
    conn.execute("DELETE FROM beam_reference WHERE beam_id = %s", (beam_id,))
    conn.execute("DELETE FROM beams WHERE id = %s", (beam_id,))
    out = {"drafts": row["n"], "legacy": n_legacy}
    conn.execute("INSERT INTO audit_log(user_id, action, entity, entity_id, details) VALUES (%s, 'delete_beam_with_drafts', 'beams', %s, %s)",
                 (actor, str(beam_id), Jsonb(out)))
    return out


def admin_purge(conn, scope: str, actor: int, reason: str) -> dict:
    """The controlled purge of measurements and/or the imported journals (admin only, a reason is required, the audit log stays)."""
    if reason is None or len(reason.strip()) < 5:
        raise MaintenanceError("a reason of at least 5 characters is required")
    if not conn.execute("SELECT 1 FROM users WHERE id = %s AND role = 'admin' AND is_active", (actor,)).fetchone():
        raise MaintenanceError("only an active admin may purge data")
    if scope not in ("measurements", "legacy", "all"):
        raise MaintenanceError(f"unknown purge scope: {scope}")
    n_res = n_ses = n_leg = 0
    _flag(conn, True)
    try:
        if scope in ("measurements", "all"):
            n_res = conn.execute("DELETE FROM results").rowcount
            n_ses = conn.execute("DELETE FROM measurement_sessions").rowcount
        if scope in ("legacy", "all"):
            n_leg = conn.execute("DELETE FROM legacy_journal").rowcount
    finally:
        _flag(conn, False)
    out = {"sessions": n_ses, "results": n_res, "legacy": n_leg}
    conn.execute("INSERT INTO audit_log(user_id, action, entity, details) VALUES (%s, 'purge', %s, %s)",
                 (actor, scope, Jsonb({"reason": reason, **out})))
    return out
