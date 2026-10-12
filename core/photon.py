"""TRS-398 Rev.1 absorbed dose to water, high-energy photon beams.

Formulas follow the user's worksheet "TRS-398 Rev.1 HE photons v2.0.xlsm" (sheet "Расчёт" and its
named ranges), not the VBA, which only drives the spreadsheet UI.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

FORMULA_VERSION = "photon-1.0"
P0_KPA = 101.325
T0_DEFAULT_C = 22.0
TPR_MIN, TPR_MAX = 0.56, 0.82   # range covered by Table 16

_TABLES_PATH = Path(__file__).parent / "data" / "photon_tables.json"
_tables_cache: Optional[dict] = None


class OutOfRangeError(ValueError):
    """Value outside the range a table covers (the spreadsheet shows a warning instead of a result)."""


def load_tables() -> dict:
    global _tables_cache
    if _tables_cache is None:
        _tables_cache = json.loads(_TABLES_PATH.read_text(encoding="utf-8"))
    return _tables_cache


def interpolate(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """Linear interpolation, xs ascending. Raises OutOfRangeError outside [xs[0], xs[-1]]."""
    if x < xs[0] or x > xs[-1]:
        raise OutOfRangeError(f"{x} is outside the table range {xs[0]}..{xs[-1]}")
    for i in range(1, len(xs)):
        if xs[i] >= x:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + (ys[i] - ys[i - 1]) * t
    return ys[-1]


def mean(values: Sequence[float] | float) -> float:
    if isinstance(values, (int, float)):
        return float(values)
    return sum(values) / len(values)


def beam_quality_tpr(fff: bool, pdd10: float, pdd20: Optional[float] = None) -> float:
    """TPR20,10 from percent depth doses at SSD 100 cm, 10x10 cm (TRS-398 Rev.1, 6.3.1, footnote 36)."""
    if fff:
        return -0.7898 + 0.0329 * pdd10 - 0.000166 * pdd10 ** 2
    if pdd20 is None:
        raise ValueError("PDD(20) is required for flattened beams")
    return 1.2661 * (pdd20 / pdd10) - 0.0595


def k_tp(pressure_kpa: float, temp_c: float, p0: float = P0_KPA, t0: float = T0_DEFAULT_C) -> float:
    return (p0 / pressure_kpa) * (273.2 + temp_c) / (273.2 + t0)


def k_pol(m_plus: float, m_minus: float, m_user: float, k_pol_q0: float = 1.0) -> float:
    """(|M+| + |M-|) / (2 M); divided by kpol(Q0) when Q differs from Q0."""
    return ((abs(m_plus) + abs(m_minus)) / (2 * m_user)) / k_pol_q0


def ks_coefficients(v_ratio: float, pulsed_scanned: bool) -> tuple[float, float, float]:
    rows = load_tables()["table10"]
    key = "pulsed_scanned" if pulsed_scanned else "pulsed"
    xs = [r["v_ratio"] for r in rows]
    return tuple(interpolate(v_ratio, xs, [r[key][i] for r in rows]) for i in range(3))  # type: ignore[return-value]


def k_s(m1: float, m2: float, v1: float, v2: float, pulsed_scanned: bool = False) -> float:
    a0, a1, a2 = ks_coefficients(v1 / v2, pulsed_scanned)
    r = m1 / m2
    return a0 + a1 * r + a2 * r ** 2


def k_vol(fff: bool, tpr: float, ref_distance_cm: float, zref: float, cavity_length_cm: Optional[float]) -> float:
    """Volume-averaging correction, applied to flattening-filter-free beams only (Table 11 / eq. 22)."""
    if not fff or cavity_length_cm is None:
        return 1.0
    rid = ref_distance_cm + zref
    return 1 + (0.0062 * tpr - 0.0036) * (100 / rid) ** 2 * cavity_length_cm ** 2


def chamber(chamber_id: int) -> dict:
    for c in load_tables()["chambers"]:
        if c["id"] == chamber_id:
            return c
    raise KeyError(f"unknown chamber id {chamber_id}")


def k_q(chamber_id: int, tpr: float) -> float:
    if not (TPR_MIN <= tpr <= TPR_MAX):
        raise OutOfRangeError(f"TPR20,10 = {tpr:.4f} is outside Table 16 range {TPR_MIN}-{TPR_MAX}")
    t = load_tables()
    return interpolate(tpr, t["tpr_nodes"], chamber(chamber_id)["kq"])


@dataclass
class PhotonInput:
    chamber_id: int
    nd_w: float                          # Gy/nC (calibration coefficient)
    mu: float
    pressure_kpa: float
    temp_c: float
    v1: float
    v2: float
    m1: Sequence[float]                  # readings at V1, user polarity
    m2: Sequence[float]                  # readings at V2
    tpr: float                           # beam quality TPR20,10
    fff: bool
    pdd_zref: Optional[float] = None     # percent, for SSD
    tmr_zref: Optional[float] = None     # for SAD (the old way: dose at zmax through the TMR)
    expected_cgy_mu: Optional[float] = None   # SAD: dose per MU expected at the reference point (planning system), cGy/MU
    m_plus: Optional[Sequence[float]] = None
    m_minus: Optional[Sequence[float]] = None
    k_elec: float = 1.0
    k_pol_q0: float = 1.0
    m_pol: Optional[Sequence[float]] = None   # M at the user's polarity for kpol; default: m1
    m1_ks: Optional[Sequence[float]] = None   # M1 at V1 for ks; default: m1
    pulsed_scanned: bool = False
    zref: float = 10.0                   # g/cm2
    ref_distance_cm: float = 100.0       # SSD
    p0_kpa: float = P0_KPA
    t0_c: float = T0_DEFAULT_C
    geometry: str = "SSD"


@dataclass
class PhotonResult:
    k_tp: float
    k_elec: float
    k_pol: float
    k_s: float
    k_vol: float
    k_q: float
    m_corrected: float                   # nC/MU
    dw_zref: float                       # Gy/MU
    dw_zmax: Optional[float]             # Gy/MU
    deviation_pct: Optional[float]       # vs 1 cGy/MU
    formula_version: str = FORMULA_VERSION
    tables_version: str = field(default_factory=lambda: load_tables()["tables_version"])


def calculate(inp: PhotonInput) -> PhotonResult:
    ch = chamber(inp.chamber_id)
    m1 = mean(inp.m1)
    m2 = mean(inp.m2)

    ktp = k_tp(inp.pressure_kpa, inp.temp_c, inp.p0_kpa, inp.t0_c)
    if inp.m_plus is not None and inp.m_minus is not None:
        kpol = k_pol(mean(inp.m_plus), mean(inp.m_minus), mean(inp.m_pol) if inp.m_pol else m1, inp.k_pol_q0)
    else:
        kpol = 1.0
    ks = k_s(mean(inp.m1_ks) if inp.m1_ks else m1, m2, inp.v1, inp.v2, inp.pulsed_scanned)
    kvol = k_vol(inp.fff, inp.tpr, inp.ref_distance_cm, inp.zref, ch["cavity_length_cm"])
    kq = k_q(inp.chamber_id, inp.tpr)

    m_corr = (m1 / inp.mu) * ktp * inp.k_elec * kpol * ks * kvol
    dw_zref = abs(m_corr) * inp.nd_w * kq

    dw_zmax = None
    if inp.geometry == "SSD" and inp.pdd_zref:
        dw_zmax = 100 * dw_zref / inp.pdd_zref
    elif inp.geometry == "SAD" and inp.tmr_zref:
        dw_zmax = dw_zref / inp.tmr_zref
    if inp.geometry == "SAD" and inp.expected_cgy_mu:      # the dose at the reference point itself, compared with the planning system value
        deviation = (dw_zref * 100 / inp.expected_cgy_mu - 1) * 100
    else:
        deviation = None if dw_zmax is None else (dw_zmax - 0.01) / 0.01 * 100

    return PhotonResult(ktp, inp.k_elec, kpol, ks, kvol, kq, m_corr, dw_zref, dw_zmax, deviation)
