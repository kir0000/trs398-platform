"""tools/make_demo_release.py: a clean database with two linacs (3 photon + 5 electron beams at SSD; 3 photon beams at SAD), coupled drift (3-5 months up to 2 % on one linac, 6 months on the other) and re-adjustments."""
import gzip
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_demo_database_is_clean_and_drifts_and_recovers(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_demo_release.py"), "--out", str(tmp_path), "--years", "3"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    assert r.returncode == 0, r.stderr[-800:]
    (gz,) = tmp_path.glob("trs398_demo_*.db.gz")
    db = tmp_path / "d.db"
    db.write_bytes(gzip.open(gz).read())
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert c.execute("SELECT count(*) FROM linacs").fetchone()[0] == 2
    assert c.execute("SELECT count(*) FROM beams WHERE modality = 'photon'").fetchone()[0] == 6
    assert c.execute("SELECT count(*) FROM beams WHERE modality = 'electron'").fetchone()[0] == 5
    assert c.execute("SELECT count(*) FROM measurement_sessions").fetchone()[0] == 11 * 36
    assert c.execute("SELECT count(*) FROM users WHERE is_active").fetchone()[0] == 0           # no working accounts
    sad = c.execute("""SELECT b.id, b.ref_depth, b.tmr_zref, b.exp_cgy_mu, s.geometry, s.ref_key, s.pdd_zref FROM beams b JOIN linacs l ON l.id = b.linac_id
                       JOIN measurement_sessions s ON s.beam_id = b.id WHERE l.name LIKE '%SAD' GROUP BY b.id""").fetchall()
    assert len(sad) == 3
    for _, depth, tmr, expected, geometry, ref_key, pdd in sad:                                 # SAD, the reference point at 10 cm, 1 cGy/MU at dmax as in TG-51
        assert (depth, geometry, pdd) == (10, "SAD", None) and tmr is None and 0.6 < expected < 0.8 and ref_key.startswith("SAD|z=10|")
    for beam_id, in c.execute("SELECT id FROM beams").fetchall():
        dev = [d for d, in c.execute("""SELECT r.deviation_pct FROM results r JOIN measurement_sessions s ON s.id = r.session_id
                                        WHERE s.beam_id = ? ORDER BY s.measured_on""", (beam_id,))]
        assert 1.5 <= max(abs(d) for d in dev) <= 2.8                                           # drifted to about 2 %
        assert all(abs(d) < 1.0 for d in dev[-2:])                                              # and is near 0 again at the end

    def series(linac):
        return [[d for d, in c.execute("""SELECT r.deviation_pct FROM results r JOIN measurement_sessions s ON s.id = r.session_id JOIN beams b ON b.id = s.beam_id
                                          JOIN linacs l ON l.id = b.linac_id WHERE l.name = ? AND b.id = ? ORDER BY s.measured_on""", (linac, bid))]
                for bid, in c.execute("SELECT b.id FROM beams b JOIN linacs l ON l.id = b.linac_id WHERE l.name = ?", (linac,)).fetchall()]

    def corr(x, y):
        mx, my = sum(x) / len(x), sum(y) / len(y)
        sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
        return sxy / (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    one, other = series("Demo Linac"), series("Demo Linac SAD")
    assert all(corr(one[0], s_) > 0.8 for s_ in one[1:])                                         # the energies of one linac move together
    assert max(abs(corr(a, b)) for a in one for b in other) < 0.7                                # the other linac is independent

