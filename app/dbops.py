"""Maintenance operations that remove history (the SECURITY DEFINER functions of the PostgreSQL edition).

Each one checks who acts, does its work in the caller's transaction and writes the audit record itself.
They raise MaintenanceError with a message; the guard triggers of the schema stay in force for everything else.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db import Jsonb, audit


class MaintenanceError(Exception):
    pass


def _flag(conn, on: bool) -> None:
    if on:
        conn.execute("INSERT OR IGNORE INTO _maintenance(k) VALUES ('purge')")
    else:
        conn.execute("DELETE FROM _maintenance WHERE k = 'purge'")


def delete_draft(conn, session_id: int, actor: int) -> str:
    """A draft or a returned record is deleted (by its author or an admin); the protocol number is not reused. Returns the number."""
    conn.lock()                                        # the status is checked and the record deleted without another writer in between
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


def prune_audit(conn, actor: int, keep_days: int, reason: str, archive_dir: Path, safety_dir: Path) -> dict:
    """The controlled clearing of the audit log (admin only, a reason is required).

    Before anything is deleted the whole log is written to a CSV archive and the database is copied to `safety_dir` (the clearing can be
    undone by restoring that copy). Records older than `keep_days` days go (0: all of them); the records about earlier clearings are never
    deleted; the clearing itself is written to the log with the name and the checksum of the archive."""
    from app import auditlog, backups                                  # here: these modules import dbops' neighbours
    if reason is None or len(reason.strip()) < 5:
        raise MaintenanceError("a reason of at least 5 characters is required")
    if not conn.execute("SELECT 1 FROM users WHERE id = %s AND role = 'admin' AND is_active", (actor,)).fetchone():
        raise MaintenanceError("only an active admin may clear the audit log")
    if keep_days < 0:
        raise MaintenanceError("the number of days to keep cannot be negative")
    rows, total = auditlog.search(conn, auditlog.parse_filters({}), limit=None)
    if not total:
        raise MaintenanceError("the audit log is empty")
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=keep_days)).isoformat(sep=" ", timespec="seconds")
    where = "action <> 'audit_pruned'" + (" AND at < %s" if keep_days else "")
    args = (cutoff,) if keep_days else ()
    doomed = conn.execute(f"SELECT min(at) AS first, max(at) AS last, count(*) AS n FROM audit_log WHERE {where}", args).fetchone()
    if not doomed["n"]:
        raise MaintenanceError("there are no records older than that")
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"audit_{datetime.now():%Y-%m-%d_%H%M%S}.csv"
    data = auditlog.to_csv(conn, rows)
    archive.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    safety_dir.mkdir(parents=True, exist_ok=True)
    safety = backups.make(folder=safety_dir, name_prefix="trs398_before_audit_clear")
    _flag_audit(conn, True)
    try:
        deleted = conn.execute(f"DELETE FROM audit_log WHERE {where}", args).rowcount
    finally:
        _flag_audit(conn, False)
    kept = conn.execute("SELECT count(*) AS n FROM audit_log").fetchone()["n"]
    out = {"deleted": deleted, "kept": kept + 1, "keep_days": keep_days, "reason": reason.strip(), "archive": archive.name, "sha256": digest,
           "safety_copy": safety.name, "first": str(doomed["first"])[:10], "last": str(doomed["last"])[:10]}
    audit(conn, actor, "audit_pruned", "audit", None, out)
    return {**out, "archive_path": str(archive)}


def _flag_audit(conn, on: bool) -> None:
    if on:
        conn.execute("INSERT OR IGNORE INTO _maintenance(k) VALUES ('audit_prune')")
    else:
        conn.execute("DELETE FROM _maintenance WHERE k = 'audit_prune'")
