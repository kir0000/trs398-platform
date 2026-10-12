"""What may be typed into the cells: the table of fields, the server limits, the attributes the page script reads."""
import re

import pytest

from tests.test_app import client, post, q, world  # noqa: F401  (fixtures are discovered here)


def test_the_table_of_fields_is_consistent(client):
    from app import fields
    for name, f in fields.FIELDS.items():
        if f.kind == "num":
            assert f.lo is not None and f.hi is not None and f.lo < f.hi, name
            if f.tlo is not None:
                assert f.lo <= f.tlo < f.thi <= f.hi + 1e-9, name          # the typical range lies inside the hard limits
        if f.kind == "text" and f.pattern:
            re.compile(f.pattern)
        a = fields.attrs(name)
        assert f'data-kind="{f.kind}"' in a and a.startswith(" ")
    assert fields.attrs("no_such_field") == ""
    assert 'data-lo="0.2"' in fields.attrs("zmax") and 'data-unit="г/см²"' in fields.attrs("zmax") and "autocomplete=\"off\"" in fields.attrs("phantom")


def test_field_size_pattern_accepts_the_usual_forms_and_rejects_the_rest(client):
    from app import fields
    for good in ("10 x 10", "10x10", "15х15", "10 × 10", "6 x 6", "12,5 x 12,5", "10 x 10 см"):
        assert fields.check_text("field_size", good) == good.strip(), good
    for bad in ("фыва", "10", "десять на десять", "10 x", "x 10", "100 x 100"):
        with pytest.raises(ValueError):
            fields.check_text("field_size", bad)
    with pytest.raises(ValueError):
        fields.check_text("phantom", "я" * 31)
    assert fields.check_text("phantom", "  ") is None and fields.check_text("phantom", "RW3") == "RW3"


def test_the_server_holds_every_beam_cell_to_its_limits(world, client):
    adm = world["adm"]
    url = f"/equipment/beam/{world['beam_id']}/params"
    cases = {"dose_rate": ("фыва", "5", "20000"), "zmax": ("ыва", "0,1", "7"), "pdd_zref": ("фыа", "20", "101"), "tmr_zref": ("x", "0,2", "1,3"),
             "cal_mu": ("фвап", "0", "20000"), "ref_depth": ("а", "0,1", "21"), "exp_cgy_mu": ("б", "0,1", "4"), "exp_zref": ("в", "0,1", "25"),
             "window_thickness": ("г", "-1", "6"), "c_pl": ("д", "0,4", "1,6"), "h_pl": ("е", "0,4", "1,6")}
    for name, bad_values in cases.items():
        for bad in bad_values:
            r = post(adm, url, {"dose_rate": "600", name: bad}, page="/equipment")
            assert r.status_code == 422, (name, bad, r.status_code)
    ok = post(adm, url, dict(dose_rate="600", zmax="1,5", pdd_zref="66,2", tmr_zref="0,669", cal_mu="200", ref_depth="10", exp_cgy_mu="0,66",
                             exp_zref="10", window_thickness="0,2", c_pl="1", h_pl="1", field_size="10 x 10", phantom="водный"), page="/equipment")
    assert ok.status_code == 303                                           # commas and points are both fine
    row = q(client, "SELECT dose_rate_mu, zmax, pdd_zref FROM beams WHERE id=%s", world["beam_id"])[0]
    assert [float(x) for x in row] == [600.0, 1.5, 66.2]
    for field, bad in (("field_size", "фыва"), ("phantom", "я" * 40), ("exp_source", "x" * 130), ("window_material", "z" * 40)):
        assert post(adm, url, {"dose_rate": "600", field: bad}, page="/equipment").status_code == 422, field


def test_linac_and_calibration_texts_and_numbers_are_checked(world, client):
    adm = world["adm"]
    assert post(adm, "/equipment/linac", dict(name="Н" * 61), page="/equipment").status_code == 422
    assert post(adm, "/equipment/linac", dict(name="Линак", serial_no="SN#!$%"), page="/equipment").status_code == 422
    assert post(adm, "/equipment/linac", dict(name="Линак 5", serial_no="LA-0042/2", city="Москва"), page="/equipment").status_code == 303
    chamber_id = q(client, "SELECT id FROM chambers ORDER BY id LIMIT 1")[0][0]
    cal = dict(chamber_id=chamber_id, serial_no="CH-9", nd_w="0.05138", calibrated_on="2026-03-01", k_elec="1")
    for field, bad in (("nd_w", "abc"), ("nd_w", "0.0001"), ("nd_w", "2"), ("k_elec", "1.6"), ("p0", "70"), ("t0", "5"), ("cal_rh", "120"),
                       ("voltage_v", "5000"), ("cal_depth", "0"), ("el_range", "x" * 21), ("lab", "л" * 61)):
        assert post(adm, "/equipment/calibration", dict(cal, **{field: bad}), page="/equipment").status_code == 422, (field, bad)
    assert post(adm, "/equipment/calibration", dict(cal, p0="101,325", t0="20", cal_rh="50", voltage_v="-300", cal_depth="5"), page="/equipment").status_code == 303


def test_pages_carry_the_rules_for_the_script(world, client):
    adm = world["adm"]
    lid = q(client, "SELECT id FROM linacs ORDER BY id LIMIT 1")[0][0]
    page = adm.get(f"/equipment?tab=beams&linac={lid}").text
    assert 'name="zmax"' in page and 'data-kind="num"' in page and 'data-lo="0.2"' in page and 'data-hi="6"' in page
    assert '<datalist id="dl-phantom">' in page and 'list="dl-phantom"' in page and 'pattern="' in page
    assert "input.invalid" in page and 'id="fieldmsg"' in page                      # the script and the message line (base.html)
    sheet = world["phys"].get("/measurements/new?modality=photon").text
    for name in ("pressure", "temp", "humidity", "mu", "pdd10"):
        assert re.search(rf'name="{name}"[^>]*data-kind="num"', sheet), name
    assert re.search(r'name="m1"[^>]*data-kind="series"', sheet)
    assert 'data-lo="80"' in sheet and 'data-hi="110"' in sheet                    # the same limits as the server (P, kPa)
    cal = adm.get("/equipment?tab=dosimeters").text
    assert 'name="nd_w"' in cal and 'data-label="ND,w"' in cal


def test_restored_values_are_not_taken_for_saved_ones(world, client):
    """The browser restores typed values after a reload; the page discards them (and the forms ask not to be restored)."""
    lid = q(client, "SELECT id FROM linacs ORDER BY id LIMIT 1")[0][0]
    page = world["adm"].get(f"/equipment?tab=beams&linac={lid}").text
    assert "el.defaultValue" in page and "autocomplete', 'off'" in page and "pageshow" in page and "beforeunload" in page
