"""Reference values of a beam: saved from the worksheet, offered to new measurements; PDD/TMR(zref) live in Equipment."""
import pytest

from tests.test_app import PHOTON, client, post, q, world  # noqa: F401  (fixtures are discovered here)

REF = dict(tpr="0,6119", mu="200", m1="24,36 24,36 24,36", m1_v1="25,8762 25,8832 25,8871", m_plus="25,8658 25,8728 25,8767",
           m_minus="25,8762 25,8832 25,8871", m2="25,7168 25,7237 25,7276", v1="-300", v2="-100")


def ref_url(world_, source="auto"):
    return f"/measurements/reference?beam_id={world_['beam_id']}&calibration_id={world_['cal_id']}&source={source}"


def test_reference_values_are_saved_and_offered(world, client):
    phys = world["phys"]
    assert phys.get(ref_url(world, "saved")).json() == {"found": False, "kind": "saved"}
    data = dict(REF, beam_id=world["beam_id"], calibration_id=world["cal_id"])
    assert post(phys, "/measurements/reference", data).status_code == 200
    got = phys.get(ref_url(world)).json()
    assert got["found"] and got["kind"] == "saved" and got["m_plus"] == REF["m_plus"] and got["mu"] == "200" and got["tpr"] == "0,6119"
    assert q(client, "SELECT count(*) FROM audit_log WHERE action='beam_reference'")[0][0] >= 1
    new = dict(REF, m_plus="25,9 25,9 25,9", beam_id=world["beam_id"], calibration_id=world["cal_id"])
    assert post(phys, "/measurements/reference", new).status_code == 200                      # replaced, not duplicated
    assert q(client, "SELECT count(*) FROM beam_reference")[0][0] == 1
    assert phys.get(ref_url(world, "saved")).json()["m_plus"] == "25,9 25,9 25,9"


def test_reference_values_are_validated_and_guarded(world):
    phys = world["phys"]
    base = dict(REF, beam_id=world["beam_id"], calibration_id=world["cal_id"])
    assert post(phys, "/measurements/reference", dict(base, m_plus="abc")).status_code == 422
    assert post(phys, "/measurements/reference", dict(base, tpr="5")).status_code == 422
    assert post(phys, "/measurements/reference", dict(base, m_plus="", m_minus="", m2="")).status_code == 422
    assert post(phys, "/measurements/reference", dict(base, beam_id="999999")).status_code == 404
    assert post(world["view"], "/measurements/reference", base).status_code == 403
    assert post(world["rev"], "/measurements/reference", base).status_code == 403


def test_pdd_and_tmr_of_the_beam_are_equipment_data(world, client):
    adm, page = world["adm"], "/equipment"
    bid = world["beam_id"]
    r = post(adm, f"/equipment/beam/{bid}/params", dict(dose_rate="600", pdd_zref="66,3", tmr_zref="0,712"), page=page)
    assert r.status_code == 303
    assert [float(x) for x in q(client, "SELECT pdd_zref, tmr_zref FROM beams WHERE id=%s", bid)[0]] == pytest.approx([66.3, 0.712])
    assert 'name="pdd_zref" value="66,3"' in adm.get(page).text
    form = world["phys"].get("/measurements/new?modality=photon").text
    assert 'data-pddz="66.3"' in form and 'data-tmrz="0.712"' in form                     # the new sheet is filled from them
    assert post(adm, f"/equipment/beam/{bid}/params", dict(dose_rate="600", pdd_zref="500"), page=page).status_code == 422


def test_new_sheet_has_the_default_humidity_and_the_range_hint(world):
    html = world["phys"].get("/measurements/new?modality=photon&lang=ru").text
    assert 'name="humidity" value="50,0"' in html or 'name="humidity" value="50"' in html
    assert "20–80 %" in html and 'id="rh_warn"' in html
    assert world["phys"].get("/measurements/new?modality=photon&lang=en").text.count("Outside 20–80 %") >= 1


def test_the_first_approved_record_offers_quality_and_mu_like_the_saved_reference(world, client):
    from tests.test_app import create_measurement
    sid = int(create_measurement(world).headers["location"].rsplit("/", 1)[1])
    page = f"/measurements/{sid}"
    post(world["phys"], f"{page}/submit", page=page)
    post(world["rev"], f"{page}/approve", {"comment": "ok"}, page=page)
    import psycopg
    with psycopg.connect(client.owner_url) as conn:
        conn.execute("DELETE FROM beam_reference")
        conn.commit()
    got = world["phys"].get(ref_url(world)).json()
    assert got["kind"] == "first" and got["mu"] == "200" and got["pdd10"] and "m_plus" in got            # the same fields as the saved one
