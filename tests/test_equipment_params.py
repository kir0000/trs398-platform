"""Parameters of worksheet sections 1-3 live in Equipment; the calculation sheet shows them but cannot change them.

Also: kelec only when the electrometer was calibrated separately, and the (iii)/(iv) readings of the beam's first
determination (editable on the sheet).
"""
import re

import psycopg
import pytest

from core import photon as ph
from tests.test_app import PHOTON, client, create_measurement, post, q, world  # noqa: F401  (fixtures are discovered here)

PG = "/measurements"
CAL = dict(serial_no="EQ-1", nd_w="0.05138", calibrated_on="2026-03-01", lab="ВНИИФТРИ", q0="Co-60", cal_depth="5",
           p0="101,3", t0="21", cal_rh="50", voltage_v="-300", pol_cal_minus="1", pol_user_minus="1",
           cal_pol_corrected="1", el_model="PTW UNIDOS", el_sn="E-1", el_range="Medium")


def chamber_id(client_):
    return q(client_, "SELECT id FROM chambers WHERE name='Sun Nuclear SNC600c Farmer'")[0][0]


def add_calibration(world_, client_, **over):
    data = dict(CAL, chamber_id=chamber_id(client_))
    data.update(over)
    assert post(world_["adm"], "/equipment/calibration", data, page=PG).status_code == 303, data
    return q(client_, "SELECT cal.id FROM calibrations cal JOIN chamber_units cu ON cu.id = cal.chamber_unit_id "
                      "WHERE cu.serial_no=%s ORDER BY cal.id DESC", data["serial_no"])[0][0]


def result(client_, sid):
    return q(client_, "SELECT k_tp, k_elec, k_pol, k_s, m_corrected, dw_zmax FROM results WHERE session_id=%s", sid)[0]


def make(world_, **over):
    r = create_measurement(world_, "phys", **over)
    assert r.status_code == 303, r.text[:300]
    return int(r.headers["location"].rsplit("/", 1)[1])


# --------------------------------------------------------------------------- the sheet shows, Equipment holds
def test_form_shows_equipment_values_but_has_no_inputs_for_them(world):
    html = world["phys"].get("/measurements/new?modality=photon").text
    for name in ("polarity_cal", "polarity_user", "t0", "p0", "cal_rh", "cal_depth", "dose_rate", "field_size", "phantom",
                 "electrometer_range", "electrometer_model", "city", "zmax", "r50_q0", "q0_is_co60", "c_pl", "h_pl"):
        assert f'name="{name}"' not in html, name
    for cell in ("e_city", "e_rate", "e_field", "e_phantom", "e_p0", "e_t0", "e_rh", "e_depth", "e_zmax", "pc_plus", "pc_minus",
                 "pc_corr", "pu_plus", "pu_minus", "el_range", "kelec_note", "kelec_row2"):
        assert f'id="{cell}"' in html, cell
    # what is entered on the sheet: the measurement itself and the (iii)/(iv) readings
    for name in ("m1", "m_plus", "m_minus", "m1_v1", "m2", "v1", "v2", "pressure", "temp", "mu"):
        assert f'name="{name}"' in html, name
    assert 'id="refbtn"' in html and 'id="refnote"' in html and 'data-new="1"' in html


def test_electron_form_shows_phantom_and_q0_from_equipment(world):
    html = world["phys"].get("/measurements/new?modality=electron").text
    for cell in ("e_cpl", "e_hpl", "e_r50q0", "cal_q0"):
        assert f'id="{cell}"' in html, cell
    for name in ("c_pl", "h_pl", "q0_is_co60", "r50_q0"):
        assert f'name="{name}"' not in html, name


def test_calibration_options_carry_the_equipment_data(world, client):
    cid = add_calibration(world, client)
    html = world["phys"].get("/measurements/new?modality=photon").text
    opt = re.search(rf'<option value="{cid}"[^>]*>', html).group(0)
    for attr, value in (("data-depth", "5"), ("data-p0", "101.3"), ("data-t0", "21"), ("data-rh", "50"), ("data-polcal", "−"),
                        ("data-poluser", "−"), ("data-polcorr", "1"), ("data-elrange", "Medium"), ("data-elsn", "E-1")):
        assert f'{attr}="{value}"' in opt, (attr, opt)


def test_the_browser_cannot_override_equipment_values(world, client):
    cid = add_calibration(world, client, serial_no="EQ-2")
    assert post(world["adm"], f"/equipment/beam/{world['beam_id']}/params",
                dict(dose_rate="1400", field_size="10 х 10", phantom="водный", zmax="1,3"), page=PG).status_code == 303
    sid = make(world, calibration_id=cid, t0="10", p0="90", field_size="подделка", dose_rate="1", cal_depth="99",
               polarity_cal="+", phantom="вода-подделка")
    form = q(client, "SELECT extra->'form' FROM measurement_sessions WHERE id=%s", sid)[0][0]
    assert (form["t0"], form["p0"], form["cal_depth"], form["polarity_cal"]) == ("21", "101,3", "5", "−")
    assert (form["field_size"], form["dose_rate"], form["phantom"], form["zmax"]) == ("10 х 10", "1400", "водный", "1,3")
    assert form["electrometer_model"] == "PTW UNIDOS" and form["electrometer_sn"] == "E-1" and form["cal_pol_corrected"] == "1"
    k_tp = float(result(client, sid)[0])
    assert k_tp == pytest.approx(ph.k_tp(100.63, 23.0, 101.3, 21.0), rel=1e-9)             # T0 = 21 from the calibration
    assert k_tp != pytest.approx(ph.k_tp(100.63, 23.0, 90.0, 10.0), rel=1e-3)


# --------------------------------------------------------------------------- kelec only for a separate calibration
def test_kelec_applies_only_when_the_electrometer_was_calibrated_separately(world, client):
    plain = add_calibration(world, client, serial_no="EQ-3", k_elec="0.9800")
    separate = add_calibration(world, client, serial_no="EQ-4", k_elec="0.9800", kelec_separate="1", kelec_lab="ВНИИФТРИ",
                               kelec_date="2026-02-10")
    assert float(result(client, make(world, calibration_id=plain))[1]) == 1.0
    assert float(result(client, make(world, calibration_id=separate))[1]) == pytest.approx(0.98)
    # the live cell shows the same value
    d = dict(PHOTON, beam_id=world["beam_id"], calibration_id=separate)
    html = post(world["phys"], "/measurements/preview", d, page=PG).text
    assert re.search(r'id="live_kelec"[^>]*>([^<]*)<', html).group(1) == "0,9800"
    d["calibration_id"] = plain
    assert re.search(r'id="live_kelec"[^>]*>([^<]*)<', post(world["phys"], "/measurements/preview", d, page=PG).text).group(1) == "1,0000"


def test_separate_calibration_requires_kelec_and_electron_q0_requires_r50(world, client):
    cid = chamber_id(client)
    base = dict(CAL, chamber_id=cid, serial_no="EQ-5")
    assert post(world["adm"], "/equipment/calibration", dict(base, kelec_separate="1"), page=PG).status_code == 422
    assert post(world["adm"], "/equipment/calibration", dict(base, q0="электронный пучок"), page=PG).status_code == 422
    assert post(world["adm"], "/equipment/calibration", dict(base, q0="электронный пучок", r50_q0="6,3"), page=PG).status_code == 303
    assert post(world["adm"], "/equipment/calibration", dict(base, serial_no="EQ-6", p0="500"), page=PG).status_code == 422


# --------------------------------------------------------------------------- (iii) and (iv) from the first determination
def test_kpol_and_ks_can_use_their_own_series(world, client):
    cid = add_calibration(world, client, serial_no="EQ-7")
    ref = dict(m_user="24,36 24,36 24,36", m1_v1="24,36 24,36 24,36", m_plus="24,35 24,35 24,35", m_minus="24,36 24,36 24,36",
               m2="24,21 24,21 24,21")
    # today's reading differs a lot from the reference series: corrections must come from the reference
    sid = make(world, calibration_id=cid, m1="30 30 30", **ref)
    k_tp, k_elec, k_pol, k_s, m_corr, dw = result(client, sid)
    assert float(k_pol) == pytest.approx(0.9997947454844008, rel=1e-9)
    assert float(k_s) == pytest.approx(1.002995640684285, rel=1e-9)
    assert float(m_corr) == pytest.approx(30 / 200 * float(k_tp) * float(k_elec) * float(k_pol) * float(k_s) * 1.0012404555388057,
                                          rel=1e-6)
    # no separate M field any more: M at the user's polarity (here "−") is the M− series, which is 24,36 as in the reference,
    # so kpol does not depend on today's 30 nC
    plain = make(world, calibration_id=cid, m1="30 30 30", m2="24,21 24,21 24,21", m_plus="24,35 24,35 24,35",
                 m_minus="24,36 24,36 24,36")
    assert float(result(client, plain)[2]) == pytest.approx(float(k_pol), rel=1e-12)


def approved_measurement(world, client, **over):
    sid = make(world, **over)
    assert post(world["phys"], f"/measurements/{sid}/submit", page=PG).status_code == 303
    assert post(world["rev"], f"/measurements/{sid}/approve", page=PG).status_code == 303
    return sid


def test_reference_series_come_from_the_first_approved_measurement_of_the_beam(world, client):
    adm = world["adm"]
    assert post(adm, "/equipment/linac", dict(name="Опорный"), page=PG).status_code == 303
    lid = q(client, "SELECT id FROM linacs WHERE name='Опорный'")[0][0]
    assert post(adm, "/equipment/beam", dict(linac_id=lid, modality="photon", energy="6", fff="1"), page=PG).status_code == 303
    bid = q(client, "SELECT id FROM beams WHERE linac_id=%s", lid)[0][0]
    cid = add_calibration(world, client, serial_no="EQ-8")
    phys = world["phys"]
    url = f"/measurements/reference?beam_id={bid}&calibration_id={cid}"
    assert phys.get(url).json() == {"found": False, "kind": "first"}                                            # nothing approved yet

    first = approved_measurement(world, client, beam_id=bid, calibration_id=cid, measured_on="2026-01-10",
                                 m1="24,36 24,36 24,36", m2="24,21 24,21 24,21", m_plus="24,35 24,35 24,35",
                                 m_minus="24,36 24,36 24,36")
    approved_measurement(world, client, beam_id=bid, calibration_id=cid, measured_on="2026-02-10", m1="24,40 24,40 24,40",
                         m2="24,25 24,25 24,25", m_plus="24,39 24,39 24,39", m_minus="24,40 24,40 24,40")
    ref = phys.get(url).json()
    assert ref["found"] and ref["record"] == first and ref["date"] == "10.01.2026"             # the first, not the latest
    assert ref["m1_v1"] == "24,36 24,36 24,36" and "m_user" not in ref
    assert (ref["m_plus"], ref["m_minus"], ref["m2"], ref["v1"], ref["v2"]) == (
        "24,35 24,35 24,35", "24,36 24,36 24,36", "24,21 24,21 24,21", "-300", "-100")
    assert ref["pulsed_scanned"] == ""
    assert world["view"].get(url).status_code == 403                                           # only those who can enter data
    assert phys.get(f"/measurements/reference?beam_id={bid}").json()["found"] is True            # calibration is optional
    # the edit form of a stored record is not auto-filled (data-new is only set for new records)
    html = phys.get(f"/measurements/{make(world, beam_id=bid, calibration_id=cid)}/edit").text
    assert 'data-new=""' in html


# --------------------------------------------------------------------------- the Equipment page
def test_equipment_page_holds_the_parameter_forms(world, client):
    lid = q(client, "SELECT id FROM linacs ORDER BY id LIMIT 1")[0][0]
    assert post(world["adm"], "/equipment/beam", dict(linac_id=lid, modality="electron", energy="9"), page=PG).status_code == 303
    beams = world["adm"].get(f"/equipment?tab=beams&linac={lid}").text
    for name in ("dose_rate", "field_size", "phantom", "c_pl", "h_pl", "zmax", "pdd_zref", "cal_mu", "exp_cgy_mu", "window_material", "city"):
        assert f'name="{name}"' in beams, name
    dosimeters = world["adm"].get("/equipment?tab=dosimeters").text
    for name in ("pol_cal_plus", "pol_cal_minus", "cal_pol_corrected", "pol_user_plus", "pol_user_minus", "el_model", "el_sn", "el_range",
                 "kelec_separate", "k_elec", "kelec_lab", "kelec_date", "r50_q0", "cal_depth", "voltage_v"):
        assert f'name="{name}"' in dosimeters, name
    assert world["adm"].get("/equipment?tab=reference").status_code == 200
    for tab in ("beams", "dosimeters", "reference"):                       # everybody can look, nobody but the administrator can change
        page = world["phys"].get(f"/equipment?tab={tab}")
        assert page.status_code == 200 and "Изменять оборудование может администратор" in page.text
        assert "Добавить калибровку" not in page.text and "Добавить пучок" not in page.text


def test_beam_parameters_are_edited_by_the_administrator_only(world, client):
    bid = world["beam_id"]
    url = f"/equipment/beam/{bid}/params"
    assert post(world["view"], url, dict(dose_rate="500"), page=PG).status_code == 403
    assert post(world["rev"], url, dict(dose_rate="500"), page=PG).status_code == 403
    assert post(world["phys"], url, dict(dose_rate="600"), page=PG).status_code == 403             # a physicist uses the equipment, the administrator edits it
    assert post(world["adm"], url, dict(dose_rate="600", field_size="10 х 10", phantom="водный", zmax="1,5"), page=PG).status_code == 303
    row = q(client, "SELECT dose_rate_mu, field_size, phantom, zmax FROM beams WHERE id=%s", bid)[0]
    assert (float(row[0]), row[1], row[2], float(row[3])) == (600.0, "10 х 10", "водный", 1.5)
    assert post(world["adm"], url, dict(dose_rate="abc"), page=PG).status_code == 422
    assert post(world["adm"], url, dict(c_pl="9"), page=PG).status_code == 422


def test_polarity_check_boxes_are_stored_as_signs(world, client):
    cid = add_calibration(world, client, serial_no="EQ-9", pol_cal_plus="1", pol_cal_minus="1", pol_user_minus="")
    assert q(client, "SELECT polarity_cal, polarity_user, cal_pol_corrected FROM calibrations WHERE id=%s", cid)[0] == ("+−", None, True)


def test_unused_calibration_can_be_edited_a_used_one_cannot(world, client):
    cid = add_calibration(world, client, serial_no="EQ-10")
    assert world["phys"].get(f"/equipment/calibration/{cid}/edit").status_code == 403
    page = world["adm"].get(f"/equipment/calibration/{cid}/edit").text
    assert 'name="nd_w"' in page and 'value="0,05138"' in page and 'name="pol_user_minus" value="1" checked' in page
    upd = dict(CAL, serial_no="x", nd_w="0.0521", pol_cal_plus="1", pol_cal_minus="", k_elec="0.99", kelec_separate="1")
    assert post(world["phys"], f"/equipment/calibration/{cid}/edit", upd, page=PG).status_code == 403
    assert post(world["adm"], f"/equipment/calibration/{cid}/edit", upd, page=PG).status_code == 303
    row = q(client, "SELECT nd_w, polarity_cal, kelec_separate, k_elec FROM calibrations WHERE id=%s", cid)[0]
    assert (float(row[0]), row[1], row[2], float(row[3])) == (0.0521, "+", True, 0.99)
    assert post(world["view"], f"/equipment/calibration/{cid}/edit", upd, page=PG).status_code == 403
    make(world, calibration_id=cid)                                                               # now it is used
    r = post(world["adm"], f"/equipment/calibration/{cid}/edit", upd, page=PG)
    assert r.status_code == 409 and "новую калибровку" in r.text
    assert "Открыть" in world["adm"].get("/equipment?tab=dosimeters").text
    assert "менять её нельзя" in world["adm"].get(f"/equipment/calibration/{cid}/edit").text


def test_linac_city_is_stored(world, client):
    adm = world["adm"]
    assert post(adm, "/equipment/linac", dict(name="С городом", city="Димитровград, Россия"), page=PG).status_code == 303
    assert q(client, "SELECT city FROM linacs WHERE name='С городом'")[0][0] == "Димитровград, Россия"
    lid = q(client, "SELECT id FROM linacs WHERE name='С городом'")[0][0]
    assert post(adm, f"/equipment/linac/{lid}/rename", dict(name="С городом", city="Москва"), page=PG).status_code == 303
    assert q(client, "SELECT city FROM linacs WHERE id=%s", lid)[0][0] == "Москва"


def test_protocol_shows_polarity_correction_and_the_separate_electrometer_calibration(world, client):
    cid = add_calibration(world, client, serial_no="EQ-11", k_elec="0.9987", kelec_separate="1", kelec_lab="ВНИИФТРИ",
                          kelec_date="2026-02-10", pol_cal_plus="1", pol_cal_minus="1", pol_user_minus="1", pol_user_plus="")
    ref = dict(m_user="24,36 24,36 24,36", m1_v1="24,36 24,36 24,36", m2="24,21 24,21 24,21",
               m_plus="24,35 24,35 24,35", m_minus="24,36 24,36 24,36")
    sid = make(world, calibration_id=cid, m1="30 30 30", **ref)
    html = world["phys"].get(f"/measurements/{sid}/print").text
    assert '<span class="ck"><b>☑</b> +</span><span class="ck"><b>☑</b> −</span><span class="ck"><b>☑</b> с поправкой на полярность</span>' in html
    assert '<span class="ck"><b>☐</b> +</span><span class="ck"><b>☑</b> −</span></div>' in html            # user polarity: minus only
    assert "если да, то калибр. лаборатория" in html and "ВНИИФТРИ" in html and "10.02.2026" in html
    assert "24,360" in html and "1,0030" in html and "0,9987" in html                                       # M1 (iv), ks and kelec


# --------------------------------------------------------------------------- dates cannot lie in the future
def test_calibration_and_measurement_dates_cannot_be_in_the_future(world, client):
    import datetime as dt
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    cid = chamber_id(client)
    base = dict(CAL, chamber_id=cid, serial_no="EQ-FUT")
    assert post(world["adm"], "/equipment/calibration", dict(base, calibrated_on=tomorrow), page=PG).status_code == 422
    assert post(world["adm"], "/equipment/calibration", dict(base, kelec_date=tomorrow), page=PG).status_code == 422
    # "valid until" is naturally in the future
    assert post(world["adm"], "/equipment/calibration", dict(base, valid_until=tomorrow), page=PG).status_code == 303
    r = create_measurement(world, measured_on=tomorrow)
    assert r.status_code == 422 and "позже сегодняшней" in r.text


# --------------------------------------------------------------------------- expired calibrations cannot be chosen
def test_expired_calibration_is_disabled_in_the_list_and_rejected_by_the_server(world, client):
    import datetime as dt
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    today = dt.date.today().isoformat()
    old = add_calibration(world, client, serial_no="EQ-OLD", calibrated_on="2024-01-01", valid_until=yesterday)
    ok = add_calibration(world, client, serial_no="EQ-OK", valid_until=today)          # valid through today
    open_end = add_calibration(world, client, serial_no="EQ-OPEN")                      # no end date: no limit
    page = world["phys"].get("/measurements/new?modality=photon").text
    option = lambda cid: re.search(rf'<option value="{cid}"[^>]*>[^<]*', page).group(0)
    assert "disabled" in option(old) and "срок истёк" in option(old)
    assert "disabled" not in option(ok) and "disabled" not in option(open_end)
    r = create_measurement(world, calibration_id=old)
    assert r.status_code == 422 and "Срок действия калибровки" in r.text
    assert create_measurement(world, calibration_id=ok).status_code == 303
    assert create_measurement(world, calibration_id=open_end).status_code == 303


def test_quality_source_is_shown_and_entered_value_wins(world, client):
    def cell(**over):
        d = dict(PHOTON, beam_id=world["beam_id"], calibration_id=world["cal_id"], pdd10="63.3", pdd20="35.07")
        d.update(over)
        html = post(world["phys"], "/measurements/preview", d, page=PG).text
        return re.search(r'id="live_qsrc" class="c ([^"]*)"[^>]*>([^<]*)<', html).groups(), \
            re.search(r'id="live_q"[^>]*>([^<]*)<', html).group(1)
    (cls, text), q_val = cell(tpr="")
    assert "qpdd" in cls and "рассчитано по PDD" in text and q_val != "—"
    (cls, text), q_val = cell(tpr="0,6277")
    assert "qin" in cls and text == "введено вручную" and q_val == "0,6277"
    (cls, text), q_val = cell(tpr="0,5000")
    assert "qwarn" in cls and "проверьте" in text and q_val == "0,5000"       # entered value is used, but flagged
    (cls, text), _ = cell(tpr="", pdd10="")
    assert text in ("", "—")


# --------------------------------------------------------------------------- phantom window (electron worksheet, section 3)
def test_phantom_window_comes_from_equipment_into_form_and_protocol(world, client):
    assert post(world["adm"], "/equipment/beam", dict(linac_id=q(client, "SELECT id FROM linacs ORDER BY id LIMIT 1")[0][0],
                                                      modality="electron", energy="11"), page=PG).status_code == 303
    bid = q(client, "SELECT id FROM beams WHERE modality='electron' AND nominal_energy=11 ORDER BY id DESC")[0][0]
    r = post(world["adm"], f"/equipment/beam/{bid}/params", dict(window_material="ПММА", window_thickness="0,2",
                                                                  phantom="RW3", c_pl="0,975", h_pl="1,01"), page="/equipment")
    assert r.status_code == 303
    assert q(client, "SELECT window_material, window_thickness FROM beams WHERE id=%s", bid)[0] == ("ПММА", 0.2) or \
        q(client, "SELECT window_material FROM beams WHERE id=%s", bid)[0][0] == "ПММА"
    assert post(world["adm"], f"/equipment/beam/{bid}/params", dict(window_thickness="99"), page="/equipment").status_code == 422
    page = world["phys"].get("/measurements/new?modality=electron").text
    assert 'data-winm="ПММА"' in page and 'id="e_winm"' in page and 'id="e_plastic"' in page


def test_form_explains_how_q_is_obtained_for_both_filter_types(world):
    page = world["phys"].get("/measurements/new?modality=photon").text
    assert 'id="qhint_fff"' in page and 'id="qhint_flt"' in page and "не нужен" in page
    assert "disabled = fff" in page                                  # PDD(20) is switched off for flattening-filter-free beams


# --------------------------------------------------------------------------- series statistics and M at the user's polarity
def test_series_drift_and_status():
    from app.services import series_stats
    flat = series_stats([24.30, 24.30, 24.30])
    assert flat["drift_pct"] == pytest.approx(0) and flat["status"] == "ok"
    rising = series_stats([100.0, 100.5, 101.0, 101.5])           # +1.5 % over the series
    assert rising["drift_pct"] == pytest.approx(1.5 / 100.75 * 100, rel=1e-6) and rising["status"] == "err"
    falling = series_stats([100.0, 99.8, 99.6])
    assert falling["drift_pct"] < 0 and falling["status"] == "warn"
    assert series_stats([24.3, 24.2]) is None and series_stats([]) is None


def test_m_at_user_polarity_comes_from_m_plus_or_m_minus():
    from app.services import user_polarity_series
    both = dict(m_plus="1 1 1", m_minus="2 2 2")
    assert user_polarity_series(dict(both, polarity_user="+")) == "1 1 1"
    assert user_polarity_series(dict(both, polarity_user="−")) == "2 2 2"
    assert user_polarity_series(dict(both, polarity_user="-")) == "2 2 2"
    assert user_polarity_series(dict(both, polarity_user="+−")) is None        # ambiguous: section 3 series is used
    assert user_polarity_series(dict(both)) is None
    assert user_polarity_series(dict(both, polarity_user="+", m_user="9 9 9")) == "9 9 9"     # records saved earlier keep theirs


def test_preview_shows_drift_cells_with_status(world):
    d = dict(PHOTON, beam_id=world["beam_id"], calibration_id=world["cal_id"], m1="24,3 24,2 24,6 24,6 24,9 24,6 26,6")
    html = post(world["phys"], "/measurements/preview", d, page=PG).text
    cell = re.search(r'id="live_dr_m1" class="c ([^"]*)"[^>]*>([^<]*)<', html)
    assert cell and "st-err" in cell.group(1) and "%" in cell.group(2)
    steady = dict(d, m1="24,36 24,36 24,36")
    cell = re.search(r'id="live_dr_m1" class="c ([^"]*)"[^>]*>([^<]*)<', post(world["phys"], "/measurements/preview", steady, page=PG).text)
    assert "st-ok" in cell.group(1)


# --------------------------------------------------------------------------- ND,w plausibility hint
def test_nd_w_hint_flags_typos_by_chamber_type():
    from app.services import nd_w_warning
    assert nd_w_warning("Capintec PR-06C Farmer", 0.0526) is None            # a normal Farmer value
    assert "0,55" in nd_w_warning("Capintec PR-06C Farmer", 0.55)            # tenfold too large
    assert nd_w_warning("Capintec PR-06C Farmer", 0.00526) is not None       # tenfold too small
    assert nd_w_warning("PTW 34001 Roos", 0.5791) is None and nd_w_warning("PTW 34001 Roos", 0.05) is not None
    assert nd_w_warning("PTW 31016 PinPoint 3D [b]", 5.0) is None            # classes without a known range are not judged
    assert nd_w_warning("Unknown chamber", 9) is None and nd_w_warning("PTW 34001 Roos", "x") is None


def test_nd_w_hint_is_shown_on_the_equipment_page_and_in_the_form(world, client):
    add_calibration(world, client, serial_no="EQ-TYPO", nd_w="0.55")
    page = world["phys"].get("/equipment?tab=dosimeters").text
    assert "⚠ проверьте" in page and "вне типичного диапазона" in page
    form = world["phys"].get("/measurements/new?modality=photon").text
    assert 'data-ndwarn="ND,w = 0,55' in form and 'id="cal_nd_warn"' in form


# --------------------------------------------------------------------------- protocol number (assigned by the database)
def test_protocol_numbers_are_sequential_unique_automatic_and_fixed(world, client):
    cid = add_calibration(world, client, serial_no="EQ-PNO")
    ids = [make(world, calibration_id=cid, measured_on=d, **extra)
           for d, extra in (("2025-03-10", {}), ("2025-03-11", {"note": "2025-9999 ввожу вручную"}), ("2024-12-31", {}))]
    nums = [q(client, "SELECT protocol_no FROM measurement_sessions WHERE id=%s", i)[0][0] for i in ids]
    assert nums[0].startswith("2025-") and nums[1].startswith("2025-") and nums[2].startswith("2024-")
    assert int(nums[1].split("-")[1]) == int(nums[0].split("-")[1]) + 1          # sequential within the year
    assert len(set(nums)) == 3 and all(len(n.split("-")[1]) == 4 for n in nums)
    # a number cannot be typed in, nor changed afterwards (not even by an owner-level update)
    sid = make(world, calibration_id=cid, measured_on="2025-03-12", protocol_no="2025-0001")
    assert q(client, "SELECT protocol_no FROM measurement_sessions WHERE id=%s", sid)[0][0] != "2025-0001"
    with psycopg.connect(client.owner_url) as conn:
        conn.execute("UPDATE measurement_sessions SET protocol_no = '1999-0001' WHERE id = %s", (ids[0],))
        conn.commit()
    assert q(client, "SELECT protocol_no FROM measurement_sessions WHERE id=%s", ids[0])[0][0] == nums[0]
    # the number is shown in the list, on the record page, on the printed protocol and in the form of a draft
    assert nums[0] in world["phys"].get("/measurements").text
    assert f"Протокол № {nums[0]}" in world["phys"].get(f"/measurements/{ids[0]}").text
    assert nums[0] in world["phys"].get(f"/measurements/{ids[0]}/print").text
    assert nums[0] in world["phys"].get(f"/measurements/{ids[0]}/edit").text
    new_form = world["phys"].get("/measurements/new?modality=photon").text
    assert "присваивается автоматически" in new_form and "№ протокола):" not in new_form


def test_a_failed_save_does_not_burn_a_number(world, client):
    cid = add_calibration(world, client, serial_no="EQ-PNO2")
    before = q(client, "SELECT last FROM protocol_counters WHERE year = 2023")
    assert create_measurement(world, calibration_id=cid, measured_on="2023-05-05", mu="0").status_code == 422   # rejected by validation
    assert q(client, "SELECT last FROM protocol_counters WHERE year = 2023") == before
    make(world, calibration_id=cid, measured_on="2023-05-05")
    assert q(client, "SELECT last FROM protocol_counters WHERE year = 2023")[0][0] == (before[0][0] + 1 if before else 1)


# --------------------------------------------------------------------------- the user guide inside the application
def test_help_page_shows_the_user_guide_to_every_signed_in_role(world):
    for who in ("view", "phys", "rev", "adm"):
        r = world[who].get("/help")
        assert r.status_code == 200 and "Руководство пользователя" in r.text and "Номер протокола" in r.text, who
        assert '<table>' in r.text and 'href="/help"' in r.text                    # tables rendered, link in the menu
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app, follow_redirects=False).get("/help").status_code == 303
