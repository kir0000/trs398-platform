"""Removing a wrong record: drafts are deleted, approved records are annulled (never deleted)."""
from tests import sqlcompat
import pytest

from tests.test_app import client, create_measurement, post, q, world  # noqa: F401  (fixtures are discovered here)


def new_record(world_, who="phys"):
    return int(create_measurement(world_, who).headers["location"].rsplit("/", 1)[1])


def approve(world_, sid):
    page = f"/measurements/{sid}"
    assert post(world_["phys"], f"{page}/submit", page=page).status_code == 303
    assert post(world_["rev"], f"{page}/approve", {"comment": "ok"}, page=page).status_code == 303


def test_a_draft_is_deleted_by_its_author_and_the_number_is_not_reused(world, client):
    sid = new_record(world)
    no = q(client, "SELECT protocol_no FROM measurement_sessions WHERE id=%s", sid)[0][0]
    page = f"/measurements/{sid}"
    assert "Удалить" in world["phys"].get(page).text and "Удалить" not in world["view"].get(page).text
    assert post(world["view"], f"{page}/delete", page=page).status_code == 403
    assert post(world["rev"], f"{page}/delete", page=page).status_code == 403
    assert post(world["phys"], f"{page}/delete", page=page).status_code == 303
    assert q(client, "SELECT count(*) FROM measurement_sessions WHERE id=%s", sid)[0][0] == 0
    assert q(client, "SELECT count(*) FROM results WHERE session_id=%s", sid)[0][0] == 0
    assert world["phys"].get(page).status_code == 404
    assert q(client, "SELECT json_extract(details, '$.protocol_no') FROM audit_log WHERE action='delete_draft' AND entity_id=%s", str(sid))[0][0] == no
    again = new_record(world)
    assert q(client, "SELECT protocol_no FROM measurement_sessions WHERE id=%s", again)[0][0] != no      # the number is burnt


def test_only_the_author_or_an_admin_deletes_and_never_an_approved_record(world, client):
    sid = new_record(world)
    page = f"/measurements/{sid}"
    other = new_record(world, "adm")
    assert post(world["phys"], f"/measurements/{other}/delete", page=page).status_code == 403      # somebody else's draft
    assert post(world["adm"], f"{page}/delete", page=page).status_code == 303                       # an admin may
    sid = new_record(world)
    approve(world, sid)
    page = f"/measurements/{sid}"
    assert post(world["adm"], f"{page}/delete", page=page).status_code == 409
    with sqlcompat.connect(client.app_url) as conn:                                                   # not even by calling the function
        from app import dbops
        with pytest.raises(dbops.MaintenanceError):
            conn.row_factory = __import__('app.db', fromlist=['x'])._dict_row
            dbops.delete_draft(conn, sid, 1)
        conn.rollback()
        with pytest.raises(sqlcompat.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM measurement_sessions WHERE id = %s", (sid,))


def test_an_approved_record_is_voided_by_an_admin_with_a_reason(world, client):
    sid = new_record(world)
    approve(world, sid)
    page = f"/measurements/{sid}"
    assert "Аннулировать" in world["adm"].get(page).text and "Аннулировать" not in world["phys"].get(page).text
    assert post(world["phys"], f"{page}/void", {"reason": "ошибка ввода давления"}, page=page).status_code == 403
    assert post(world["adm"], f"{page}/void", {"reason": "ab"}, page=page).status_code == 422
    assert post(world["adm"], f"{page}/void", {"reason": "ошибка ввода давления"}, page=page).status_code == 303
    assert q(client, "SELECT status FROM measurement_sessions WHERE id=%s", sid)[0][0] == "voided"
    assert q(client, "SELECT count(*) FROM v_trend WHERE source='measured' AND record_id=%s", sid)[0][0] == 0           # gone from the trends
    assert "аннулирована" in world["phys"].get(page).text
    assert "АННУЛИРОВАНО" in world["phys"].get(f"{page}/print").text
    assert post(world["adm"], f"{page}/void", {"reason": "ещё раз ошибка"}, page=page).status_code == 409
    assert q(client, "SELECT count(*) FROM audit_log WHERE action='void' AND entity_id=%s", str(sid))[0][0] == 1
    with sqlcompat.connect(client.app_url) as conn:                                                   # a voided record stays voided
        with pytest.raises(sqlcompat.errors.RaiseException):
            conn.execute("UPDATE measurement_sessions SET status = 'approved' WHERE id = %s", (sid,))


def test_voiding_a_correction_makes_the_replaced_record_valid_again(world, client):
    sid = new_record(world)
    approve(world, sid)
    page = f"/measurements/{sid}"
    r = post(world["phys"], f"{page}/supersede", {"reason": "уточнение данных"}, page=page)
    new_id = int(r.headers["location"].split("/")[2])
    approve(world, new_id)
    assert q(client, "SELECT status FROM measurement_sessions WHERE id=%s", sid)[0][0] == "superseded"
    assert post(world["adm"], f"/measurements/{new_id}/void", {"reason": "правка была ошибочной"}, page=page).status_code == 303
    assert q(client, "SELECT status FROM measurement_sessions WHERE id=%s", sid)[0][0] == "approved"
