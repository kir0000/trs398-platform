"""The Equipment section: tabs, readiness of a beam, calibration state, back links, reference values, roles."""
import datetime as dt
import sys
from pathlib import Path

from tests import sqlcompat
import pytest
from tests.sqlcompat import dict_row
from tests.test_app import client, post, q, world  # noqa: F401  (fixtures are discovered here)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_beam_readiness_names_what_is_missing(client):
    from app.main import beam_readiness
    empty = dict(zmax=None, pdd_zref=None, field_size="", dose_rate_mu=None, cal_mu=None)
    assert beam_readiness(empty) == {"hard": ["zmax", "PDD(zref)"], "soft": ["размер поля", "референсная глубина", "мощность дозы", "MU при калибровке"], "state": "bad"}
    soft = dict(empty, zmax=1.5, pdd_zref=66)
    assert beam_readiness(soft)["state"] == "warn" and beam_readiness(soft)["hard"] == []
    full = dict(soft, field_size="10 x 10", dose_rate_mu=600, cal_mu=200, ref_depth=10)
    assert beam_readiness(full) == {"hard": [], "soft": [], "state": "ok"}


def test_calibration_state_expired_soon_ok(client):
    from app.main import calibration_state
    today = dt.date(2026, 10, 12)
    assert calibration_state({"valid_until": dt.date(2026, 10, 1)}, today) == {"state": "expired", "days": -11}
    assert calibration_state({"valid_until": dt.date(2026, 12, 1)}, today)["state"] == "soon"
    assert calibration_state({"valid_until": dt.date(2028, 2, 1)}, today)["state"] == "ok"
    assert calibration_state({"valid_until": None}, today) == {"state": "none", "days": None}


def test_back_link_stays_inside_the_equipment_section(client):
    from app.main import eq_back
    class Form(dict):
        pass
    assert eq_back(Form(back="/equipment?tab=dosimeters")) == "/equipment?tab=dosimeters"
    assert eq_back(Form(back="/equipment?tab=beams&linac=3")) == "/equipment?tab=beams&linac=3"
    for bad in ("//evil.example", "https://evil.example", "/admin/users", "", "/equipment//x"):
        assert eq_back(Form(back=bad)) == "/equipment", bad
    assert eq_back(Form()) == "/equipment"


def test_tabs_show_one_linac_at_a_time_and_remember_the_place(world, client):
    adm = world["adm"]
    assert post(adm, "/equipment/linac", dict(name="Второй аппарат", back="/equipment?tab=beams"), page="/equipment").status_code == 303
    first, second = [r[0] for r in q(client, "SELECT id FROM linacs ORDER BY id")][:2]
    assert post(adm, "/equipment/beam", dict(linac_id=second, modality="photon", energy="15", back=f"/equipment?tab=beams&linac={second}"),
                page="/equipment").headers["location"] == f"/equipment?tab=beams&linac={second}"
    only_second = adm.get(f"/equipment?tab=beams&linac={second}").text
    assert "Второй аппарат" in only_second and "15 MV" in only_second and "Фотоны" in only_second and "Электроны" in only_second
    only_first = adm.get(f"/equipment?tab=beams&linac={first}").text
    assert "15 MV" not in only_first                                      # the beams of another linac are not on the page
    r = post(adm, f"/equipment/beam/{world['beam_id']}/params", dict(dose_rate="600", back=f"/equipment?tab=beams&linac={first}"), page="/equipment")
    assert r.headers["location"] == f"/equipment?tab=beams&linac={first}&saved={world['beam_id']}#b{world['beam_id']}"      # back to the same row
    page = adm.get(r.headers["location"].split("#")[0]).text
    assert "✓ Сохранено" in page and f'id="b{world['beam_id']}" class=saved' in page and 'id="eq_dirty"' in page and 'id="eqhead"' in page
    assert "не хватает" in adm.get(f"/equipment?tab=beams&linac={first}").text         # the readiness badge


def test_reference_tab_lists_the_saved_values_and_only_the_administrator_deletes_them(world, client):
    data = dict(beam_id=world["beam_id"], calibration_id=world["cal_id"], mu="200", tpr="0,6119", m_plus="25,86 25,87 25,88", m_minus="25,87 25,88 25,89",
                m2="25,71 25,72 25,73", m1_v1="25,87 25,88 25,89", v1="-300", v2="-100")
    assert post(world["phys"], "/measurements/reference", data).status_code == 200
    page = world["view"].get("/equipment?tab=reference").text
    assert "25,86 25,87 25,88" in page and "Опорные значения пучков" in page and 'action="/equipment/reference/delete"' not in page
    adm_page = world["adm"].get("/equipment?tab=reference").text
    assert 'action="/equipment/reference/delete"' in adm_page
    unit = q(client, "SELECT chamber_unit_id FROM calibrations WHERE id=%s", world["cal_id"])[0][0]
    body = dict(beam_id=world["beam_id"], chamber_unit_id=unit, back="/equipment?tab=reference")
    assert post(world["phys"], "/equipment/reference/delete", body, page="/equipment").status_code == 403
    r = post(world["adm"], "/equipment/reference/delete", body, page="/equipment")
    assert r.status_code == 303 and r.headers["location"] == "/equipment?tab=reference"
    assert q(client, "SELECT count(*) FROM beam_reference")[0][0] == 0
    assert post(world["adm"], "/equipment/reference/delete", body, page="/equipment").status_code == 404


def test_dosimeters_tab_groups_the_calibrations_by_chamber_unit(world, client):
    page = world["adm"].get("/equipment?tab=dosimeters").text
    assert "Камеры и калибровки" in page and "Новая калибровка" in page and "Электрометры" in page
    assert page.count("SN 123456789") >= 1


# --------------------------------------------------------------------------- a beam entered by mistake
def beam_with_records(world, client, energy, approved=False):
    adm = world["adm"]
    lid = q(client, "SELECT id FROM linacs ORDER BY id LIMIT 1")[0][0]
    assert post(adm, "/equipment/beam", dict(linac_id=lid, modality="photon", energy=str(energy), fff="1"), page="/equipment").status_code == 303
    bid = q(client, "SELECT id FROM beams WHERE modality='photon' AND nominal_energy=%s AND fff", energy)[0][0]
    from tests.test_app import PHOTON
    data = dict(PHOTON, beam_id=bid, calibration_id=world["cal_id"])
    r = post(world["phys"], "/measurements", data, page="/measurements")
    assert r.status_code == 303
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    if approved:
        page = f"/measurements/{sid}"
        post(world["phys"], f"{page}/submit", page=page)
        post(world["rev"], f"{page}/approve", {"comment": "ok"}, page=page)
    return bid, sid


def test_a_beam_with_records_cannot_be_deleted_but_can_be_archived_and_restored(world, client):
    bid, sid = beam_with_records(world, client, 18)
    adm = world["adm"]
    assert post(adm, f"/equipment/beam/{bid}/delete", page="/equipment").status_code == 409
    assert "Отправьте пучок в архив" in post(adm, f"/equipment/beam/{bid}/delete", page="/equipment").text
    choices = world["phys"].get("/measurements/new?modality=photon").text
    assert f'<option value="{bid}"' in choices
    assert post(world["phys"], f"/equipment/beam/{bid}/archive", page="/equipment").status_code == 403
    assert post(adm, f"/equipment/beam/{bid}/archive", dict(back="/equipment?tab=beams"), page="/equipment").status_code == 303
    assert f'<option value="{bid}"' not in world["phys"].get("/measurements/new?modality=photon").text      # not offered any more
    lid = q(client, "SELECT linac_id FROM beams WHERE id=%s", bid)[0][0]
    page = adm.get(f"/equipment?tab=beams&linac={lid}").text
    assert "Архив пучков" in page and "Вернуть из архива" in page
    assert q(client, "SELECT count(*) FROM measurement_sessions WHERE id=%s", sid)[0][0] == 1                # the record stays
    assert post(adm, f"/equipment/beam/{bid}/archive", dict(archived="0"), page="/equipment").status_code == 303
    assert f'<option value="{bid}"' in world["phys"].get("/measurements/new?modality=photon").text


def test_a_beam_with_only_drafts_is_deleted_together_with_them(world, client):
    bid, sid = beam_with_records(world, client, 20)
    adm = world["adm"]
    assert post(world["phys"], f"/equipment/beam/{bid}/purge", page="/equipment").status_code == 403
    assert post(adm, f"/equipment/beam/{bid}/purge", page="/equipment").status_code == 303
    assert q(client, "SELECT count(*) FROM beams WHERE id=%s", bid)[0][0] == 0
    assert q(client, "SELECT count(*) FROM measurement_sessions WHERE id=%s", sid)[0][0] == 0
    assert q(client, "SELECT count(*) FROM results WHERE session_id=%s", sid)[0][0] == 0
    assert q(client, "SELECT json_extract(details, '$.drafts') FROM audit_log WHERE action='delete_beam_with_drafts' AND entity_id=%s", str(bid))[0][0] == 1


def test_approved_records_are_history_and_block_the_deletion(world, client):
    bid, sid = beam_with_records(world, client, 22, approved=True)
    adm = world["adm"]
    r = post(adm, f"/equipment/beam/{bid}/purge", page="/equipment")
    assert r.status_code == 409 and "архив" in r.text
    assert q(client, "SELECT count(*) FROM beams WHERE id=%s", bid)[0][0] == 1
    assert post(adm, f"/measurements/{sid}/void", {"reason": "пучок введён по ошибке"}, page=f"/measurements/{sid}").status_code == 303
    assert post(adm, f"/equipment/beam/{bid}/purge", page="/equipment").status_code == 409                  # an annulled record is history as well
    from tests import sqlcompat
    from app import dbops
    with sqlcompat.connect(client.app_url) as conn:                                                        # nor can the function be abused
        with pytest.raises(dbops.MaintenanceError):
            conn.row_factory = __import__('app.db', fromlist=['x'])._dict_row
            dbops.delete_beam_with_drafts(conn, bid, 1, True)


def test_imported_journal_rows_need_a_separate_confirmation(world, client):
    bid, sid = beam_with_records(world, client, 24)
    from tests import sqlcompat
    with sqlcompat.connect(client.owner_url) as conn:
        conn.execute("INSERT INTO legacy_journal(beam_id, measured_on, deviation_pct, dw_zmax, source_file) VALUES (%s, '2025-01-01', 0.1, 0.01, 'test')", (bid,))
        conn.commit()
    adm = world["adm"]
    assert post(adm, f"/equipment/beam/{bid}/purge", page="/equipment").status_code == 409
    assert post(adm, f"/equipment/beam/{bid}/purge", dict(with_legacy="1"), page="/equipment").status_code == 303
    assert q(client, "SELECT count(*) FROM legacy_journal WHERE beam_id=%s", bid)[0][0] == 0
