"""describe() asks the database once per kind of object, not once per record, and says the same words as before."""
from app import auditlog
from tests import sqlcompat
from tests.sqlcompat import dict_row
from tests.test_app import client, create_measurement, q, world  # noqa: F401  (fixtures are discovered here)


class Counting:
    def __init__(self, conn):
        self.conn, self.n = conn, 0

    def execute(self, *a, **k):
        self.n += 1
        return self.conn.execute(*a, **k)


def test_queries_do_not_grow_with_the_number_of_records(world, client):
    for _ in range(3):
        create_measurement(world, "phys")
    with sqlcompat.connect(client.owner_url, row_factory=dict_row) as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
        rows = rows * 20
        counting = Counting(conn)
        names = auditlog.describe(counting, rows)
    assert len(rows) > 100 and counting.n <= 5
    assert any(text.startswith("Протокол №") and url for text, url in names.values())
    assert any(text.startswith("Пользователь ") for text, _ in names.values())


def test_deleted_and_unknown_objects_keep_their_words():
    class Empty:
        def execute(self, *a, **k):
            class R:
                def fetchall(self_):
                    return []
            return R()
    rows = [dict(entity="beams", entity_id="99", details=None), dict(entity="linacs", entity_id="98", details=None),
            dict(entity="calibrations", entity_id="97", details=None), dict(entity="measurement", entity_id="96", details={"protocol_no": "7"}),
            dict(entity="uncertainty", entity_id="photon", details=None)]
    names = auditlog.describe(Empty(), rows)
    assert names[("beams", "99")][0] == "Пучок 99 (удалён)"
    assert names[("linacs", "98")][0] == "Аппарат 98 (удалён)"
    assert names[("calibrations", "97")][0] == "Калибровка 97 (удалена)"
    assert names[("measurement", "96")] == ("Протокол № 7", None)
    assert names[("uncertainty", "photon")][0].endswith("фотоны")
