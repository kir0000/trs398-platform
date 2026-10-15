"""Integrity audit: recompute every stored result from its raw data and compare with the results table.

Runs inside the app container (the calculation core lives there); the database is only read:
    docker exec -i trs398_app python - < tools/recompute_check.py
    (PowerShell has no '<': Get-Content tools/recompute_check.py -Raw | docker exec -i trs398_app python -)

Exit code 0: every record reproduces within 1e-9 (relative); otherwise the differing records are listed.
"""
import sys

from app import db, services
from app.main import form_values

FIELDS = ("k_tp", "k_elec", "k_pol", "k_s", "k_vol", "k_q", "m_corrected", "dw_zref", "dw_zmax", "deviation_pct")
TOL = 1e-9

conn = db.connect()
rows = conn.execute("""
    SELECT s.*, b.modality, ch.name AS chamber
    FROM measurement_sessions s JOIN beams b ON b.id = s.beam_id
    JOIN calibrations cal ON cal.id = s.calibration_id JOIN chamber_units cu ON cu.id = cal.chamber_unit_id
    JOIN chambers ch ON ch.id = cu.chamber_id
    JOIN results r ON r.session_id = s.id ORDER BY s.id""").fetchall()
checked = skipped = 0
bad = []
for row in rows:
    row["extra"] = row["extra"] or {}
    form = form_values(row)
    beam = conn.execute("SELECT * FROM beams WHERE id = %s", (row["beam_id"],)).fetchone()
    calib = conn.execute("SELECT * FROM calibrations WHERE id = %s", (row["calibration_id"],)).fetchone()
    stored = conn.execute("SELECT * FROM results WHERE session_id = %s", (row["id"],)).fetchone()
    try:
        _, res, _, _ = services.compute(row["modality"], dict(form), beam, calib, row["chamber"])
    except Exception as e:                            # noqa: BLE001 - report, do not stop the audit
        bad.append((row["id"], f"cannot recompute: {e}"))
        continue
    checked += 1
    diffs = [f"{k}: stored {stored[k]}, now {res[k]}" for k in FIELDS if (stored[k] is None) != (res[k] is None)]     # SAD with an expected dose has no Dw(zmax)
    diffs += [f"{k}: stored {float(stored[k]):.10g}, now {float(res[k]):.10g}" for k in FIELDS
              if stored[k] is not None and res[k] is not None and abs(float(stored[k]) - float(res[k])) > TOL * max(1.0, abs(float(stored[k])))]
    if diffs:
        bad.append((row["id"], "; ".join(diffs)))
print(f"records with results: {len(rows)}, recomputed: {checked}, skipped: {skipped}")
for sid, why in bad[:50]:
    print(f"  #{sid}: {why}")
print("OK: every stored result reproduces from the raw data" if not bad else f"MISMATCH in {len(bad)} record(s)")
sys.exit(1 if bad else 0)
