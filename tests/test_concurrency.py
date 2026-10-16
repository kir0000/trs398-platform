"""Several people work at the same time: the handlers do not block the event loop, a record is decided once, nothing is lost."""
import threading

from app import db
from tests import sqlcompat
from tests.test_app import client, create_measurement, post, q, world  # noqa: F401  (fixtures are discovered here)


def new_submitted(world_):
    sid = int(create_measurement(world_, "phys").headers["location"].rsplit("/", 1)[1])
    assert post(world_["phys"], f"/measurements/{sid}/submit", {}, page=f"/measurements/{sid}").status_code == 303
    return sid


def test_two_reviewers_cannot_both_approve_the_same_record(world, client):
    sid = new_submitted(world)
    results = []

    def approve():
        results.append(post(world["rev"], f"/measurements/{sid}/approve", {}, page=f"/measurements/{sid}").status_code)
    threads = [threading.Thread(target=approve) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) in ([303, 409], [409, 409]) or results.count(303) == 1, results
    assert q(client, f"SELECT count(*) FROM audit_log WHERE action = 'approve' AND entity_id = '{sid}'")[0][0] == 1


def test_a_record_that_was_decided_meanwhile_cannot_be_decided_again_or_edited(world, client):
    sid = new_submitted(world)
    assert post(world["rev"], f"/measurements/{sid}/approve", {}, page=f"/measurements/{sid}").status_code == 303
    assert post(world["rev"], f"/measurements/{sid}/approve", {}, page=f"/measurements/{sid}").status_code in (403, 409)
    assert post(world["rev"], f"/measurements/{sid}/return", {"comment": "поздно"}, page=f"/measurements/{sid}").status_code in (403, 409)
    assert post(world["phys"], f"/measurements/{sid}/delete", {}, page=f"/measurements/{sid}").status_code == 409
    assert q(client, f"SELECT status FROM measurement_sessions WHERE id = {sid}")[0][0] == "approved"


def test_delete_and_submit_at_the_same_time_leave_one_consistent_result(world, client):
    sid = int(create_measurement(world, "phys").headers["location"].rsplit("/", 1)[1])
    out = {}

    def submit():
        out["submit"] = post(world["phys"], f"/measurements/{sid}/submit", {}, page=f"/measurements/{sid}").status_code

    def delete():
        out["delete"] = post(world["phys"], f"/measurements/{sid}/delete", {}, page=f"/measurements/{sid}").status_code
    threads = [threading.Thread(target=submit), threading.Thread(target=delete)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    left = q(client, f"SELECT status FROM measurement_sessions WHERE id = {sid}")
    assert (not left and out["delete"] in (303, 200)) or (left and left[0][0] == "submitted" and out["delete"] == 409), (out, left)


def test_the_handlers_run_in_threads_not_on_the_event_loop():
    import inspect
    from app.routes import admin, equipment, measurements, pages, trends, uncertainty
    for module in (admin, equipment, measurements, pages, trends, uncertainty):
        asynchronous = [n for n, f in vars(module).items() if inspect.iscoroutinefunction(f) and n != "form_data"]
        assert not asynchronous, f"{module.__name__}: {asynchronous}"
