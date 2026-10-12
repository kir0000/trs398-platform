"""The protocol appendix "Uncertainty estimate" («Оценка неопределённости»; basis: the electron worksheet's analysis sheet)."""
import datetime as dt
import math
from dataclasses import asdict
from decimal import Decimal as D

import pytest

from app import protocol
from core import electron as el
from core import photon as ph
from core import spc

HISTORY = [(dt.date(2024, 1, 15) + dt.timedelta(days=30 * i), round(0.15 * math.sin(i) + 0.012 * i - 0.1, 3))
           for i in range(30)]
COMMON = dict(id=1, measured_on=dt.date(2026, 9, 19), geometry="SSD", humidity_pct=D(50), tmr_zref=None, note="",
              cal_k_elec=D(1), cal_lab="Лаб", calibrated_on=dt.date(2026, 2, 1), creator="А", approver="Б",
              approved_at=dt.datetime(2026, 9, 20), status="approved", linac="L", cal_q0="Co-60")


def photon_case():
    r = ph.calculate(ph.PhotonInput(chamber_id=26, nd_w=0.05138, mu=200, pressure_kpa=100.63, temp_c=23, v1=-300, v2=-100,
                                    m1=[24.36] * 3, m2=[24.21] * 3, tpr=0.62763, fff=True, pdd_zref=63.3))
    s = dict(COMMON, modality="photon", mu=D(200), pressure_kpa=D("100.63"), temp_c=D(23), v1=D(-300), v2=D(-100),
             m1_readings=[D("24.36")] * 3, m2_readings=[D("24.21")] * 3, beam_quality=D("0.62763"), pdd_zref=D("63.3"),
             nominal_energy=D(6), fff=True, chamber="Sun Nuclear SNC600c Farmer", serial_no="1", nd_w=D("0.05138"),
             cal_voltage=D(-300), extra={"form": {}})
    return s, asdict(r)


def electron_case(chamber_id=1, chamber="PTW 34001 Roos", r50=3.755, co60=True):
    r = el.calculate(el.ElectronInput(chamber_id=chamber_id, nd_w=0.5791, mu=100, pressure_kpa=102.91, temp_c=21.9,
                                      v1=300, v2=100, m1=[1.883] * 4, m2=[1.887] * 4, r50_measured=r50, pdd_zref=99.95,
                                      q0_is_co60=co60, r50_q0=None if co60 else 7.0))
    res = asdict(r)
    res["k_vol"] = 1.0
    s = dict(COMMON, modality="electron", mu=D(100), pressure_kpa=D("102.91"), temp_c=D("21.9"), v1=D(300), v2=D(100),
             m1_readings=[D("1.883")] * 4, m2_readings=[D("1.887")] * 4, beam_quality=D(str(r50)), pdd_zref=D("99.95"),
             nominal_energy=D(15), fff=False, chamber=chamber, serial_no="2", nd_w=D("0.5791"), cal_voltage=D(300),
             extra={"r50w": r.r50w, "zref": r.zref, "form": {"q0_is_co60": "1" if co60 else ""}})
    return s, res


def unc(s, res, history=HISTORY):
    return protocol.build(s, res, history)["unc"]


def test_photon_budget_numbers_and_notes():
    u = unc(*photon_case())
    assert (u["u1"], u["u2"]) == ("1,35", "0,82")
    sigma = spc.analyse([spc.Point(d, v) for d, v in HISTORY]).sigma
    assert u["sigma_a"] == protocol.f(sigma, 2)
    expect_uc = math.sqrt(1.346291201783626 ** 2 + 0.818535277187245 ** 2 + sigma ** 2)
    assert u["uc"] == protocol.f(expect_uc, 2) and u["U"] == protocol.f(2 * expect_uc, 2)
    assert u["reference"] == "1,58"
    assert len(u["notes"]) == 4 and u["notes"][0].startswith("(a)") and "таблице 17" in u["notes_title"]
    assert [row[3] for row in u["stage1"]] == ["", "", "см. примечание (b)"]
    assert u["stage2"][2][3] == "см. примечание (c)" and u["stage2"][4][3] == "см. примечание (d)"
    assert any("Тип A (GUM, п. 4.2)" in d for d in u["definitions"]) and "Табл. 17" in u["definitions"][1]


def test_electron_budget_depends_on_chamber_and_r50():
    plane = unc(*electron_case(chamber_id=1, chamber="PTW 34001 Roos", r50=3.755))            # R50,w ~ 3.8
    cyl = unc(*electron_case(chamber_id=11, chamber="NE 2571", r50=3.755))
    low = unc(*electron_case(chamber_id=1, chamber="PTW 34001 Roos", r50=1.8))                # R50,w < 2
    kq = lambda u: u["stage2"][4][2]
    assert (kq(plane), kq(cyl), kq(low)) == ("0,70", "0,70", "0,80")
    assert plane["config"][1][1].startswith("плоскопараллельная") and cyl["config"][1][1].startswith("цилиндрическая")
    assert len(plane["notes"]) == 5 and plane["notes"][4].startswith("(e)")
    assert "Табл. 24" in plane["config"][2][1]
    assert "кубическим" not in plane["type_a_text"] and "Систематические компоненты" in plane["type_a_text"]
    assert plane["stage2"][4][3].startswith("см. примечание (c)") and plane["stage2"][5][3] == "см. примечание (d)"


def test_electron_calibrated_in_electron_beam_uses_table_25_values():
    u = unc(*electron_case(co60=False))
    assert [r[2] for r in u["stage1"]] == ["1,00"] and "Табл. 25" in u["config"][2][1]
    assert u["stage2"][4][2] == "0,20" and u["stage2"][5][2] == "0,10"


def test_decision_block_matches_the_worksheet_logic():
    d = unc(*electron_case())["decision"]
    params = {k: v for k, v, _ in d["params"]}
    assert params["Допуск на отклонение выхода (уровень действия), ±T"] == "2 %" and params["Плановый интервал между калибровками"] == "12 мес"
    state = {k: v for k, v, _ in d["state"]}
    assert state["Вердикт по последнему измерению"] in ("норма", "наблюдение") or state["Вердикт по последнему измерению"].startswith(("ПРЕД", "ДЕЙ"))
    assert "Как это работает" in d["intro"] and "Ограничения" in d["limits"]
    assert any(k == "Рекомендация" for k, _, _ in d["forecast"])


def test_decision_flags_an_out_of_tolerance_last_point():
    hist = HISTORY[:-1] + [(HISTORY[-1][0], 2.6)]
    state = {k: v for k, v, _ in unc(*photon_case(), history=hist)["decision"]["state"]}
    assert state["Вердикт по последнему измерению"].startswith("ДЕЙСТВИЕ")


def test_short_history_does_not_break_the_appendix():
    one = unc(*photon_case(), history=[(dt.date(2026, 9, 19), 0.1)])
    assert one["sigma_a"] == "—" and one["uc"] == one["reference"]           # no Type A yet: uc = Type B only
    assert protocol.build(*photon_case(), history=None)["unc"] is None       # no history: no appendix


def test_template_renders_the_appendix():
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from pathlib import Path
    s, res = electron_case()
    v = protocol.build(s, res, HISTORY)
    env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "app" / "templates")),
                      autoescape=select_autoescape())
    from app.notation import sym, sym_plain
    env.filters.update(sym=sym, sym_plain=sym_plain)
    html = env.get_template("protocol.html").render(s=s, res=res, v=v, screen=False, unc_mode="full",
                                                      status_labels={"approved": "утверждено"})
    for text in ("Приложение. Оценка неопределённости", "Этап 1. Поверочная лаборатория", "Тип A (GUM, п. 4.2)",
                 "Примечания к таблицам 24/25", "Решение о перекалибровке", "Расширенная неопределённость"):
        assert text in html, text


def test_short_appendix_is_compact_and_has_the_key_numbers():
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from pathlib import Path
    from app.notation import sym, sym_plain
    s, res = electron_case()
    v = protocol.build(s, res, HISTORY)
    env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "app" / "templates")), autoescape=select_autoescape())
    env.filters.update(sym=sym, sym_plain=sym_plain)
    page = lambda mode: env.get_template("protocol.html").render(s=s, res=res, v=v, screen=False, unc_mode=mode,
                                                                 status_labels={"approved": "утверждено"})
    short, full, none = page("short"), page("full"), page("none")
    assert "Оценка неопределённости (кратко)" in short and "Расширенная неопределённость" in short
    assert v["unc"]["uc"] in short and v["unc"]["U"] in short                     # u_c and U are on the page
    assert "Приложение" not in none
    assert len(short) - len(none) < 0.35 * (len(full) - len(none))                # the appendix alone: a fraction of the full one
    assert short.count("<tr") <= 24                                               # small enough for one page
