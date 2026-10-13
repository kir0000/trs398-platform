"""TRS-398 Rev.1 absorbed dose to water, high-energy electron beams (section 7).

Formulas follow the user's worksheet "TRS-398 Rev.1 HE electrons v2.0.xlsm". kQ comes from Rev.1 Tables 20
(Co-60 calibration) and 21 (electron-beam calibration), interpolated with a natural cubic spline over R50;
the table values live in the worksheet's VBA module modRev1kQ and are extracted by importers/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence


from core.photon import OutOfRangeError, k_pol, k_s, k_tp, mean

FORMULA_VERSION = "electron-1.0"
P0_KPA = 101.325
T0_DEFAULT_C = 20.0           # as in the worksheet's calibration conditions

_TABLES_PATH = Path(__file__).parent / "data" / "electron_tables.json"
_tables_cache: Optional[dict] = None


def load_tables() -> dict:
    global _tables_cache
    if _tables_cache is None:
        _tables_cache = json.loads(_TABLES_PATH.read_text(encoding="utf-8"))
    return _tables_cache


def chamber(chamber_id: int) -> dict:
    for c in load_tables()["chambers"]:
        if c["id"] == chamber_id:
            return c
    raise KeyError(f"unknown chamber id {chamber_id}")


def natural_cubic_spline(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Value at x of the natural cubic spline (second derivative zero at both ends) through the nodes (xs increasing).
    The same curve as scipy.interpolate.CubicSpline(xs, ys, bc_type="natural"), without the heavy dependency."""
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    # the second derivatives m of the nodes: a tridiagonal system solved by the Thomas algorithm
    m = [0.0] * n
    if n > 2:
        a, b, c, d = [0.0] * n, [1.0] * n, [0.0] * n, [0.0] * n
        for i in range(1, n - 1):
            a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            d[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
        for i in range(1, n):
            w = a[i] / b[i - 1]
            b[i] -= w * c[i - 1]
            d[i] -= w * d[i - 1]
        m[n - 1] = d[n - 1] / b[n - 1]
        for i in range(n - 2, -1, -1):
            m[i] = (d[i] - c[i] * m[i + 1]) / b[i]
    k = n - 2
    for i in range(n - 1):
        if x <= xs[i + 1]:
            k = i
            break
    t0, t1 = xs[k + 1] - x, x - xs[k]
    return (m[k] * t0 ** 3 + m[k + 1] * t1 ** 3) / (6 * h[k]) + (ys[k] / h[k] - m[k] * h[k] / 6) * t0 + (ys[k + 1] / h[k] - m[k + 1] * h[k] / 6) * t1


def _spline_kq(row: Optional[Sequence[Optional[float]]], r50: float) -> float:
    """Natural cubic spline over the nodes that have data; R50 must lie inside the covered range."""
    if not row:
        raise OutOfRangeError("no kQ data for this chamber in the selected table")
    grid = load_tables()["r50_grid"]
    pts = [(x, y) for x, y in zip(grid, row) if y is not None]
    if len(pts) < 2:
        raise OutOfRangeError("no kQ data for this chamber in the selected table")
    xs, ys = zip(*pts)
    if r50 < xs[0] - 1e-6 or r50 > xs[-1] + 1e-6:
        raise OutOfRangeError(f"R50 = {r50:.3f} is outside the covered range {xs[0]}-{xs[-1]} g/cm2")
    return natural_cubic_spline(xs, ys, min(max(r50, xs[0]), xs[-1]))


def k_q_co60(chamber_id: int, r50: float) -> float:
    """kQ for a chamber calibrated in Co-60 (Table 20)."""
    return _spline_kq(chamber(chamber_id)["kq_table20"], r50)


def k_q_qint(chamber_id: int, r50: float) -> float:
    """kQ,Qint for a chamber calibrated in an electron beam (Table 21)."""
    return _spline_kq(chamber(chamber_id)["kq_table21"], r50)


def beam_quality_r50w(r50_measured: float, c_pl: float = 1.0) -> float:
    """R50 in water from the measured value: c_pl * R50 * 1.029 - 0.06 (worksheet sheet Temp, cell D11)."""
    return c_pl * r50_measured * 1.029 - 0.06


def z_ref(r50w: float) -> float:
    return 0.6 * r50w - 0.1


@dataclass
class ElectronInput:
    chamber_id: int
    nd_w: float
    mu: float
    pressure_kpa: float
    temp_c: float
    v1: float
    v2: float
    m1: Sequence[float]
    m2: Sequence[float]
    r50_measured: float                  # g/cm2
    pdd_zref: Optional[float] = None     # percent at zref for the applicator
    m_plus: Optional[Sequence[float]] = None
    m_minus: Optional[Sequence[float]] = None
    k_elec: float = 1.0
    k_pol_q0: float = 1.0
    m_pol: Optional[Sequence[float]] = None   # M at the user's polarity for kpol; default: m1
    m1_ks: Optional[Sequence[float]] = None   # M1 at V1 for ks; default: m1
    c_pl: float = 1.0                    # depth scaling, plastic phantoms
    h_pl: float = 1.0                    # fluence scaling, plastic phantoms
    pulsed_scanned: bool = False
    q0_is_co60: bool = True
    r50_q0: Optional[float] = None       # R50 of the calibration beam when Q0 is an electron beam
    p0_kpa: float = P0_KPA
    t0_c: float = T0_DEFAULT_C


@dataclass
class ElectronResult:
    r50w: float
    zref: float
    k_tp: float
    k_elec: float
    k_pol: float
    k_s: float
    h_pl: float
    k_q: float
    m_corrected: float                   # nC/MU
    dw_zref: float                       # Gy/MU
    dw_zmax: Optional[float]
    deviation_pct: Optional[float]
    formula_version: str = FORMULA_VERSION
    tables_version: str = field(default_factory=lambda: load_tables()["tables_version"])


def calculate(inp: ElectronInput) -> ElectronResult:
    m1, m2 = mean(inp.m1), mean(inp.m2)
    q = beam_quality_r50w(inp.r50_measured, inp.c_pl)

    ktp = k_tp(inp.pressure_kpa, inp.temp_c, inp.p0_kpa, inp.t0_c)
    kpol = (k_pol(mean(inp.m_plus), mean(inp.m_minus), mean(inp.m_pol) if inp.m_pol else m1, inp.k_pol_q0)
            if inp.m_plus is not None and inp.m_minus is not None else 1.0)
    ks = k_s(mean(inp.m1_ks) if inp.m1_ks else m1, m2, inp.v1, inp.v2, inp.pulsed_scanned)

    if inp.q0_is_co60:
        kq = k_q_co60(inp.chamber_id, q)
    else:
        if inp.r50_q0 is None:
            raise ValueError("r50_q0 is required when Q0 is an electron beam")
        kq = k_q_qint(inp.chamber_id, q) / k_q_qint(inp.chamber_id, inp.r50_q0)

    m_corr = (m1 / inp.mu) * ktp * inp.h_pl * inp.k_elec * kpol * ks
    dw_zref = abs(m_corr) * inp.nd_w * kq
    dw_zmax = 100 * dw_zref / inp.pdd_zref if inp.pdd_zref else None
    deviation = None if dw_zmax is None else (dw_zmax - 0.01) / 0.01 * 100
    return ElectronResult(q, z_ref(q), ktp, inp.k_elec, kpol, ks, inp.h_pl, kq, m_corr, dw_zref, dw_zmax, deviation)
