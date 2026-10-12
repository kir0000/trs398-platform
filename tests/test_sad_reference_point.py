"""SAD: the dose at the reference point against the planning-system value; separate trend series per reference conditions."""
import pytest

from core import photon as ph
from tests.test_app import PHOTON, client, create_measurement, post, q, world  # noqa: F401  (fixtures are discovered here)


def approve(world_, sid):
    page = f"/measurements/{sid}"
    assert post(world_["phys"], f"{page}/submit", page=page).status_code == 303
    assert post(world_["rev"], f"{page}/approve", {"comment": "ok"}, page=page).status_code == 303


def set_expected(world_, value, zref="10", source="Monaco 6.1, 10x10, SAD 100", cal_mu="200"):
    r = post(world_["adm"], f"/equipment/beam/{world_['beam_id']}/params",
             dict(dose_rate="600", exp_cgy_mu=value, exp_zref=zref, exp_source=source, cal_mu=cal_mu), page="/equipment")
    assert r.status_code == 303


def sad_record(world_, **over):
    d = dict(PHOTON, geometry="SAD", pdd_zref="", pdd10="66", pdd20="35", beam_id=world_["beam_id"], calibration_id=world_["cal_id"])
    d.update(over)
    return post(world_["phys"], "/measurements", d, page="/measurements")


def test_core_deviation_at_the_reference_point():
    base = dict(chamber_id=1, nd_w=0.05138, mu=200, pressure_kpa=100.63, temp_c=23, v1=-300, v2=-100, m1=[24.36] * 3, m2=[24.21] * 3,
                tpr=0.6119, fff=False, m_plus=[24.35] * 3, m_minus=[24.36] * 3, geometry="SAD")
    old = ph.calculate(ph.PhotonInput(**base, tmr_zref=0.669))
    new = ph.calculate(ph.PhotonInput(**base, expected_cgy_mu=0.669))
    assert new.dw_zmax is None and new.dw_zref == old.dw_zref
    assert new.deviation_pct == pytest.approx((new.dw_zref * 100 / 0.669 - 1) * 100)
    assert new.deviation_pct == pytest.approx(old.deviation_pct, rel=1e-9)            # the same number as TMR = expected, without a TMR


def test_equipment_keeps_the_expected_dose_and_the_calibration_mu(world, client):
    set_expected(world, "0,633")
    assert [float(x) for x in q(client, "SELECT exp_cgy_mu, exp_zref, cal_mu FROM beams WHERE id=%s", world["beam_id"])[0]] == [0.633, 10.0, 200.0]
    assert q(client, "SELECT exp_source FROM beams WHERE id=%s", world["beam_id"])[0][0].startswith("Monaco")
    form = world["phys"].get("/measurements/new?modality=photon").text
    assert 'data-calmu="200"' in form and 'data-expcgy="0.633"' in form and 'id="exp_row"' in form
    assert post(world["adm"], f"/equipment/beam/{world['beam_id']}/params", dict(dose_rate="600", exp_cgy_mu="0"), page="/equipment").status_code == 422


def test_a_sad_record_is_compared_with_the_expected_dose_and_makes_its_own_series(world, client):
    set_expected(world, "0,633")
    ssd = int(create_measurement(world).headers["location"].rsplit("/", 1)[1])
    approve(world, ssd)
    r = sad_record(world)
    assert r.status_code == 303, r.text[:300]
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    row = q(client, "SELECT s.ref_key, r.dw_zmax, r.deviation_pct, r.dw_zref FROM measurement_sessions s JOIN results r ON r.session_id = s.id WHERE s.id=%s", sid)[0]
    assert row[0] == "SAD|z=10||0.633" and row[1] is None
    assert float(row[2]) == pytest.approx((float(row[3]) * 100 / 0.633 - 1) * 100)
    html = world["phys"].get(f"/measurements/{sid}").text
    assert "от ожидаемых 0,633 сГр/MU" in html and "Monaco" in html
    assert world["phys"].get(f"/measurements/{sid}/print").status_code == 200 and world["phys"].get(f"/measurements/{sid}/print?unc=full").status_code == 200
    approve(world, sid)
    page = f"/trends?beam_id={world['beam_id']}"
    html = world["view"].get(page).text
    assert "Ряд (опорные условия)" in html and "SSD" in html and "опорная точка на глубине 10" in html and "ожидаемая доза 0,633" in html
    both = [k[0] for k in q(client, "SELECT DISTINCT ref_key FROM v_trend")]
    assert "SSD" in both and "SAD|z=10||0.633" in both
    only_sad = world["view"].get(page + "&cond=SAD%7Cz%3D10%7C%7C0.633").text
    assert "<option value=\"SAD|z=10||0.633\" selected" in only_sad


def test_a_changed_expected_value_starts_another_series(world, client):
    set_expected(world, "0,64")
    sid = int(sad_record(world).headers["location"].rsplit("/", 1)[1])
    assert q(client, "SELECT ref_key FROM measurement_sessions WHERE id=%s", sid)[0][0] == "SAD|z=10||0.64"
    approve(world, sid)
    old = q(client, "SELECT count(*) FROM v_trend WHERE ref_key = 'SAD|z=10||0.633'")[0][0]
    new = q(client, "SELECT count(*) FROM v_trend WHERE ref_key = 'SAD|z=10||0.64'")[0][0]
    assert old >= 1 and new == 1                                                # the earlier values stay in their own series


def test_sad_without_an_expected_dose_still_needs_the_tmr(world, client):
    set_expected(world, "", zref="", source="")
    r = sad_record(world)
    assert r.status_code == 422                                                 # neither the expected dose nor the TMR
    assert sad_record(world, tmr_zref="0,669").status_code == 303
