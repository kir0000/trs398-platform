"""Load a journal JSON (from extract_journal.py) into legacy_journal.

Idempotent: rows are keyed by (beam, date, Dw) and duplicates are skipped.
Connection: DATABASE_URL env var (use the owner role for imports).

Usage: python importers/load_legacy.py <journal.json> --linac "Name" --modality photon|electron
           --energy 6 [--fff] --source "file name" [--demo]
"""
import argparse
import json
import os

import psycopg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("journal")
    ap.add_argument("--linac", required=True)
    ap.add_argument("--modality", choices=["photon", "electron"], required=True)
    ap.add_argument("--energy", type=float, required=True)
    ap.add_argument("--fff", action="store_true")
    ap.add_argument("--source", required=True)
    ap.add_argument("--demo", action="store_true", help="mark rows as demo data (excluded from trends)")
    a = ap.parse_args()

    entries = json.load(open(a.journal, encoding="utf-8"))
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO linacs(name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (a.linac,))
        cur.execute("SELECT id FROM linacs WHERE name = %s", (a.linac,))
        linac_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO beams(linac_id, modality, nominal_energy, fff) VALUES (%s, %s, %s, %s)
                       ON CONFLICT (linac_id, modality, nominal_energy, fff) DO NOTHING""",
                    (linac_id, a.modality, a.energy, a.fff))
        cur.execute("""SELECT id FROM beams WHERE linac_id = %s AND modality = %s
                       AND nominal_energy = %s AND fff = %s""", (linac_id, a.modality, a.energy, a.fff))
        beam_id = cur.fetchone()[0]
        added = 0
        for e in entries:
            cur.execute("""INSERT INTO legacy_journal(beam_id, measured_on, deviation_pct, dw_zmax, mq_nc_per_mu,
                                                      chamber_text, note, source_file, is_demo)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (beam_id, measured_on, dw_zmax) DO NOTHING""",
                        (beam_id, e["date"], e["deviation_pct"], e["dw_zmax"], e["mq_nc_per_mu"],
                         e["chamber"], e["note"], a.source, a.demo))
            added += cur.rowcount
        conn.commit()
    print(f"{added} of {len(entries)} entries added (beam id {beam_id}, demo={a.demo})")


if __name__ == "__main__":
    main()
