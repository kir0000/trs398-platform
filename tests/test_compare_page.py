"""The /compare page: several energies of one linac side by side."""
import datetime as dt
import json
import random
import re

import psycopg

from tests.test_app import client, post, q, world  # noqa: F401  (fixtures are discovered here)

PG = "/measurements"


def make_linac(world_, client_, name, beams, shift_month=None):
    """A linac with the given beams, 14 monthly imported (non-demo) records each; optionally one common shift."""
    assert post(world_["adm"], "/equipment/linac", dict(name=name), page=PG).status_code == 303
    lid = q(client_, "SELECT id FROM linacs WHERE name=%s", name)[0][0]
    ids = {}
    for modality, energy, fff in beams:
        assert post(world_["adm"], "/equipment/beam", dict(linac_id=lid, modality=modality, energy=str(energy),
                                                           **({"fff": "1"} if fff else {})), page=PG).status_code == 303
        ids[(modality, energy, fff)] = q(client_, "SELECT id FROM beams WHERE linac_id=%s AND modality=%s AND nominal_energy=%s AND fff=%s",
                                         lid, modality, energy, fff)[0][0]
    start = dt.date(2025, 7, 15)
    with psycopg.connect(client_.owner_url) as conn:
        for k, bid in enumerate(ids.values()):
            rng = random.Random(500 + k)
            for i in range(14):
                m = start.month - 1 + i
                d = dt.date(start.year + m // 12, m % 12 + 1, 15)
                dev = rng.gauss(0, 0.1) + (1.2 if i == shift_month else 0.0)
                conn.execute("INSERT INTO legacy_journal(beam_id, measured_on, deviation_pct, dw_zmax, source_file) VALUES (%s,%s,%s,%s,'t')",
                             (bid, d, dev, 0.01 * (1 + dev / 100)))
    return lid


def plot_of(html):
    return json.loads(re.search(r"var d = (\{.*?\});\n  var cfg", html, re.S).group(1))


def test_compare_lists_every_energy_and_finds_the_common_shift(world, client):
    lid = make_linac(world, client, "Сравнение", [("photon", 6, False), ("photon", 10, True), ("electron", 6, False),
                                                 ("electron", 9, False), ("electron", 12, False)], shift_month=8)
    html = world["view"].get(f"/compare?linac_id={lid}").text
    for energy in ("6 MV", "10 MV FFF", "6 MeV", "9 MeV", "12 MeV"):            # the table has a type column (γ / e⁻) and a beam column
        assert f"<td>{energy}</td>" in html, energy
    assert "<td>γ</td>" in html and "<td>e⁻</td>" in html
    assert "Общий сдвиг нескольких энергий" in html and "2026-03" in html and "вверх" in html
    d = plot_of(html)
    assert len(d["series"]) == 5 and len(d["months"]) == 14 and len(d["matrix"]) == 5 and len(d["matrix"][0]) == 14
    assert len(d["corr"]) == 5 and all(row[i] == 1.0 for i, row in enumerate(d["corr"]))
    for tag in ('id="overlay"', 'id="heat"', 'id="corr"'):
        assert tag in html


def test_compare_filters_by_type_and_period(world, client):
    lid = q(client, "SELECT id FROM linacs WHERE name='Сравнение'")[0][0]
    photons = world["view"].get(f"/compare?linac_id={lid}&modality=photon").text
    assert "<td>6 MV</td>" in photons and "<td>6 MeV</td>" not in photons and "<td>e⁻</td>" not in photons
    electrons = plot_of(world["view"].get(f"/compare?linac_id={lid}&modality=electron").text)
    assert [s["label"] for s in electrons["series"]] == ["e⁻ 6 MeV", "e⁻ 9 MeV", "e⁻ 12 MeV"]
    short = plot_of(world["view"].get(f"/compare?linac_id={lid}&months=6").text)
    today = dt.date.today()
    total = today.year * 12 + today.month - 1 - 6
    since = f"{total // 12:04d}-{total % 12 + 1:02d}"
    assert all(m >= since for m in short["months"]) and len(short["months"]) < 14      # only the last six months remain
    assert world["view"].get(f"/compare?linac_id={lid}&modality=x").status_code == 422
    assert world["view"].get(f"/compare?linac_id={lid}&months=7").status_code == 422
    assert world["view"].get("/compare?linac_id=99999").status_code == 404


def test_compare_without_data_and_default_linac(world, client):
    assert post(world["adm"], "/equipment/linac", dict(name="Пустой аппарат"), page=PG).status_code == 303
    lid = q(client, "SELECT id FROM linacs WHERE name='Пустой аппарат'")[0][0]
    assert "нет утверждённых данных" in world["view"].get(f"/compare?linac_id={lid}").text
    default = world["view"].get("/compare").text                              # no linac chosen: the one with the most beams
    assert "Сравнение" in default and "Состояние каждой энергии" in default


def test_compare_is_open_to_every_signed_in_role_and_pinned_in_the_menu(world):
    for who in ("view", "phys", "rev", "adm"):
        r = world[who].get("/compare")
        assert r.status_code == 200 and 'href="/compare"' in r.text, who
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app, follow_redirects=False).get("/compare").status_code == 303
