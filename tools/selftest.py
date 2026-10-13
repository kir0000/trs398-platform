"""Check that this copy of the program calculates the two worked examples of the IAEA worksheets exactly as the worksheets do
(photons 6 MV FFF, electrons 15 MeV):  TRS398.exe selftest   or   python tools/selftest.py.   Exit code 0: everything agrees."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import electron as el  # noqa: E402
from core import photon as ph  # noqa: E402


LINES: list[str] = []


def out(text: str = "") -> None:
    LINES.append(text)
    print(text)


def check(rows) -> int:
    bad = 0
    for name, got, want, rel in rows:
        ok = abs(got - want) <= rel * abs(want)
        bad += not ok
        out(f"  {'ok ' if ok else 'BAD'} {name:22} {got:.9g}  (worksheet {want:.9g})")
    return bad


def main():
    p = ph.calculate(ph.PhotonInput(chamber_id=26, nd_w=0.05138, mu=200, pressure_kpa=100.63, temp_c=23.0, v1=-300, v2=-100,
                                    m1=[24.36] * 3, m2=[24.21] * 3, tpr=0.6276262600000001, fff=True, pdd_zref=63.3,
                                    m_plus=[24.35] * 3, m_minus=[24.36] * 3, k_elec=1.0, geometry="SSD"))
    e = el.calculate(el.ElectronInput(chamber_id=1, nd_w=0.5791, mu=100, pressure_kpa=102.91, temp_c=21.9, v1=300, v2=100,
                                      m1=[1.883, 1.883, 1.883, 1.885], m2=[1.886, 1.887, 1.887, 1.887], r50_measured=3.755, pdd_zref=99.95,
                                      m_plus=[1.883, 1.883, 1.883, 1.885], m_minus=[1.888] * 4))
    out("Photons, 6 MV FFF, Farmer SNC600c")
    bad = check([("kTP", p.k_tp, 1.0103174189597408, 1e-9), ("kpol", p.k_pol, 0.9997947454844008, 1e-9),
                 ("ks", p.k_s, 1.002995640684285, 1e-9), ("kvol", p.k_vol, 1.0012404555388057, 1e-9),
                 ("kQ", p.k_q, 0.9972661618, 1e-8), ("Dw(zmax), Gy/MU", p.dw_zmax, 0.010001263894416275, 1e-8)])
    out("Electrons, 15 MeV, Roos 34001")
    bad += check([("R50,w", e.r50w, 3.8038949999999994, 1e-12), ("kTP", e.k_tp, 0.9909786038026048, 1e-9),
                  ("kpol", e.k_pol, 1.0011945845500398, 1e-9), ("ks", e.k_s, 0.9991763968174774, 1e-9),
                  ("kQ", e.k_q, 0.924415799331137, 1e-9), ("M_Q, nC/MU", e.m_corrected, 0.018671988036372746, 1e-9)])
    out("\nOK: the calculation agrees with the worksheets." if not bad else f"\nERROR: {bad} value(s) differ from the worksheets.")
    if os.environ.get("TRS_DATA"):                                  # the result is also kept for the support (the console window closes)
        try:
            (Path(os.environ["TRS_DATA"]) / "selftest.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
        except OSError:
            pass
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
