"""Golden values are the cached results of the user's electron worksheet (15 MeV example, PTW 34001 Roos)."""
import pytest

from core import electron as el
from core import photon as ph


def example(**over):
    base = dict(
        chamber_id=1, nd_w=0.5791, mu=100, pressure_kpa=102.91, temp_c=21.9, v1=300, v2=100,
        m1=[1.883, 1.883, 1.883, 1.885], m2=[1.886, 1.887, 1.887, 1.887],
        m_plus=[1.883, 1.883, 1.883, 1.885], m_minus=[1.888] * 4,
        r50_measured=3.755, pdd_zref=99.95,
    )
    base.update(over)
    return el.ElectronInput(**base)


def test_example_matches_worksheet():
    r = el.calculate(example())
    assert r.r50w == pytest.approx(3.8038949999999994, rel=1e-12)
    assert r.zref == pytest.approx(2.1823369999999995, rel=1e-12)
    assert r.k_tp == pytest.approx(0.9909786038026048, rel=1e-9)
    assert r.k_pol == pytest.approx(1.0011945845500398, rel=1e-9)
    assert r.k_s == pytest.approx(0.9991763968174774, rel=1e-9)
    assert r.k_q == pytest.approx(0.924415799331137, rel=1e-9)
    assert r.m_corrected == pytest.approx(0.018671988036372746, rel=1e-9)
    assert r.dw_zref == pytest.approx(0.009995660219860893, rel=1e-9)
    assert r.dw_zmax == pytest.approx(0.01000066055013596, rel=1e-9)


def test_spline_passes_through_table_nodes():
    row = el.chamber(1)["kq_table20"]
    grid = el.load_tables()["r50_grid"]
    assert el.k_q_co60(1, grid[4]) == pytest.approx(row[4], rel=1e-12)


def test_r50_outside_range_is_rejected():
    with pytest.raises(ph.OutOfRangeError):
        el.k_q_co60(1, 12.0)


def test_chamber_without_co60_data_is_rejected():
    with pytest.raises(ph.OutOfRangeError):
        el.k_q_co60(3, 4.0)         # Adv. Markus has no Table 20 data


def test_electron_calibration_needs_q0_r50():
    with pytest.raises(ValueError):
        el.calculate(example(q0_is_co60=False))


def test_electron_calibration_ratio():
    r = el.calculate(example(q0_is_co60=False, r50_q0=7.0))
    q = el.beam_quality_r50w(3.755)
    assert r.k_q == pytest.approx(el.k_q_qint(1, q) / el.k_q_qint(1, 7.0), rel=1e-12)
