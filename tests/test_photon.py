"""Golden values are the cached results of the user's worksheet (6 FFF example, SNC600c Farmer)."""
import pytest

from core import photon as ph

REL = 1e-9


def example_input(**over):
    base = dict(
        chamber_id=26, nd_w=0.05138, mu=200, pressure_kpa=100.63, temp_c=23.0,
        v1=-300, v2=-100, m1=[24.36] * 3, m2=[24.21] * 3, tpr=0.6276262600000001, fff=True,
        pdd_zref=63.3, m_plus=[24.35] * 3, m_minus=[24.36] * 3, k_elec=1.0, geometry="SSD",
    )
    base.update(over)
    return ph.PhotonInput(**base)


def test_example_matches_worksheet():
    r = ph.calculate(example_input())
    assert r.k_tp == pytest.approx(1.0103174189597408, rel=REL)
    assert r.k_pol == pytest.approx(0.9997947454844008, rel=REL)
    assert r.k_s == pytest.approx(1.002995640684285, rel=REL)
    assert r.k_vol == pytest.approx(1.0012404555388057, rel=REL)
    assert r.k_q == pytest.approx(0.9972661618, rel=1e-8)
    assert r.m_corrected == pytest.approx(0.12355303373799296, rel=REL)
    assert r.dw_zref == pytest.approx(0.0063308000451655026, rel=1e-8)
    assert r.dw_zmax == pytest.approx(0.010001263894416275, rel=1e-8)
    assert r.deviation_pct == pytest.approx(0.012638944162750299, rel=1e-6)


def test_tpr_from_pdd_fff_matches_worksheet():
    assert ph.beam_quality_tpr(True, 63.3) == pytest.approx(0.6276262600000001, rel=REL)


def test_tpr_from_pdd_wff():
    assert ph.beam_quality_tpr(False, 66.0, 38.0) == pytest.approx(1.2661 * 38 / 66 - 0.0595, rel=REL)


def test_wff_has_no_kvol():
    assert ph.k_vol(False, 0.7, 100, 10, 2.27) == 1.0


def test_tpr_outside_table_is_rejected():
    with pytest.raises(ph.OutOfRangeError):
        ph.calculate(example_input(tpr=0.9))


def test_without_polarity_readings_kpol_is_one():
    r = ph.calculate(example_input(m_plus=None, m_minus=None))
    assert r.k_pol == 1.0


def test_ks_interpolates_between_voltage_ratios():
    lo = ph.ks_coefficients(3.0, False)
    hi = ph.ks_coefficients(3.5, False)
    mid = ph.ks_coefficients(3.25, False)
    for a, b, c in zip(lo, hi, mid):
        assert c == pytest.approx((a + b) / 2, rel=REL)


def test_sad_uses_tmr():
    r = ph.calculate(example_input(geometry="SAD", pdd_zref=None, tmr_zref=0.63))
    assert r.dw_zmax == pytest.approx(r.dw_zref / 0.63, rel=REL)


def test_all_26_chambers_have_12_kq_nodes():
    t = ph.load_tables()
    assert len(t["chambers"]) == 26
    assert all(len(c["kq"]) == 12 for c in t["chambers"])
