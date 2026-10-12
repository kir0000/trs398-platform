"""Editable Type B values of the uncertainty budget, added lines, the appendix of the protocol, literature comparison."""
import re

import psycopg
import pytest

from core import uncertainty
from tests.test_app import client, create_measurement, post, q, world  # noqa: F401  (fixtures are discovered here)


@pytest.fixture(autouse=True)
def clean_settings(client):
    """Every test starts with the standard budget (earlier tests of the module leave their changes behind)."""
    with psycopg.connect(client.owner_url) as conn:
        conn.execute("UPDATE uncertainty_settings SET active = false")
        conn.commit()


def page_of(world_):
    return f"/uncertainty?beam_id={world_['beam_id']}"


def inputs(html):
    return {m.group(1): m.group(2) for m in re.finditer(r'name="(u_[^"]+)" value="([^"]*)"', html)}


# --------------------------------------------------------------------------- core
def test_apply_settings_replaces_values_and_adds_lines():
    base = uncertainty.photon_budget(0.2)
    edited = uncertainty.apply_settings(uncertainty.photon_budget(0.2), {"s2_kq": 0.4, "unknown": 9},
                                        [dict(code="xabc", name="Установка глубины камеры", stage=2, u_pct=0.17, note="n"),
                                         dict(code="xdef", name="Строка этапа 1", stage=1, u_pct=0.1, note="")])
    kq = next(c for c in edited.stage2 if c.code == "s2_kq")
    assert (kq.u_pct, kq.default_u) == (0.4, 0.6)
    assert edited.stage2[-1].custom and edited.stage2[-1].code == "xabc" and edited.stage1[-1].code == "xdef"
    assert edited.u2 == pytest.approx((base.u2 ** 2 - 0.6 ** 2 + 0.4 ** 2 + 0.17 ** 2) ** 0.5)
    assert edited.u1 == pytest.approx((base.u1 ** 2 + 0.1 ** 2) ** 0.5)
    same = uncertainty.apply_settings(uncertainty.photon_budget(0.2), {"s2_kq": 0.6})
    assert all(c.default_u is None for c in same.stage2)            # a value equal to the standard one changes nothing


def test_every_standard_component_has_a_unique_code():
    for b in (uncertainty.photon_budget(), uncertainty.electron_budget(True, True, 1.5), uncertainty.electron_budget(False, False, 6.0)):
        codes = [c.code for c in b.stage1 + b.stage2]
        assert all(codes) and len(codes) == len(set(codes))


# --------------------------------------------------------------------------- the page and the routes
def test_physicist_sees_inputs_viewer_sees_values_only(world):
    assert "u_s2_kq" in inputs(world["phys"].get(page_of(world)).text)
    viewer = world["view"].get(page_of(world)).text
    assert not inputs(viewer) and "Сохранить значения" not in viewer and "Сравнение с литературой" in viewer
    assert "McEwen" in viewer and "McDermott" in viewer


def test_values_can_be_changed_reset_and_validated(world, client):
    phys, page = world["phys"], page_of(world)

    def form(**over):
        return dict({"modality": "photon", "back": page, "u_s2_kq": "0,60", "d_s2_kq": "0.6000"}, **over)

    assert post(phys, "/uncertainty/settings", form(u_s2_kq="0,40"), page=page).status_code == 303
    assert float(q(client, "SELECT u_pct FROM uncertainty_settings WHERE code='s2_kq' AND active")[0][0]) == pytest.approx(0.4)
    html = phys.get(page).text
    assert inputs(html)["u_s2_kq"] == "0,40" and "по умолчанию 0,60" in html
    assert post(phys, "/uncertainty/settings", form(u_s2_kq="0,60"), page=page).status_code == 303      # back to the standard value
    assert q(client, "SELECT count(*) FROM uncertainty_settings WHERE code='s2_kq' AND active")[0][0] == 0
    assert post(phys, "/uncertainty/settings", form(u_s2_kq="11"), page=page).status_code == 422        # out of range
    assert post(phys, "/uncertainty/settings", form(u_s2_kq="abc"), page=page).status_code == 422
    assert post(phys, "/uncertainty/settings", form(modality="x"), page=page).status_code == 422
    post(phys, "/uncertainty/settings", form(u_s2_kq="0,30"), page=page)
    assert post(phys, "/uncertainty/settings/reset", dict(modality="photon", back=page), page=page).status_code == 303
    assert q(client, "SELECT count(*) FROM uncertainty_settings WHERE NOT is_extra AND active")[0][0] == 0


def test_only_physicist_and_admin_may_edit(world):
    page = page_of(world)
    for who in ("view", "rev"):
        r = post(world[who], "/uncertainty/settings", dict(modality="photon", back=page, u_s2_kq="0,1", d_s2_kq="0.6"), page=page)
        assert r.status_code == 403, who
    r = post(world["adm"], "/uncertainty/extra", dict(modality="photon", stage="2", name="Строка админа", u_new="0,1"), page=page)
    assert r.status_code == 303


def test_added_lines_are_summed_edited_and_removed(world, client):
    phys, page = world["phys"], page_of(world)
    r = post(phys, "/uncertainty/extra", dict(modality="photon", stage="2", name="Установка глубины камеры", u_new="0,17", note="TG-51", back=page),
             page=page)
    assert r.status_code == 303
    code = q(client, "SELECT code FROM uncertainty_settings WHERE is_extra AND active AND name='Установка глубины камеры'")[0][0]
    html = phys.get(page).text
    assert "Установка глубины камеры" in html and f'name="u_{code}"' in html and "добавлено" in html
    assert post(phys, "/uncertainty/extra", dict(modality="photon", stage="2", name="ab", u_new="0,1"), page=page).status_code == 422
    assert post(phys, "/uncertainty/extra", dict(modality="photon", stage="3", name="Строка", u_new="0,1"), page=page).status_code == 422
    assert post(phys, "/uncertainty/settings", {"modality": "photon", "back": page, f"u_{code}": "0,25"}, page=page).status_code == 303
    assert float(q(client, "SELECT u_pct FROM uncertainty_settings WHERE code=%s", code)[0][0]) == pytest.approx(0.25)
    assert post(phys, "/uncertainty/extra/delete", dict(modality="photon", code=code, back=page), page=page).status_code == 303
    assert "Установка глубины камеры" not in phys.get(page).text.split("Добавить свою строку")[0]
    assert post(phys, "/uncertainty/extra/delete", dict(modality="photon", code=code, back=page), page=page).status_code == 404
    assert q(client, "SELECT count(*) FROM audit_log WHERE action LIKE 'uncertainty_%%'")[0][0] >= 4


def test_modalities_are_independent_and_back_cannot_leave_the_page(world, client):
    phys, page = world["phys"], page_of(world)
    r = post(phys, "/uncertainty/settings", dict(modality="electron", back="//evil.example", u_s2_kq="0,2", d_s2_kq="0.7"), page=page)
    assert r.status_code == 303 and r.headers["location"] == "/uncertainty"
    assert q(client, "SELECT count(*) FROM uncertainty_settings WHERE modality='photon' AND code='s2_kq' AND active")[0][0] == 0
    post(phys, "/uncertainty/settings/reset", dict(modality="electron", back=page), page=page)


def test_the_protocol_appendix_uses_the_changed_values_and_marks_them(world, client):
    phys, page = world["phys"], page_of(world)
    sid = int(create_measurement(world).headers["location"].rsplit("/", 1)[1])
    assert "изменено, по умолчанию" not in phys.get(f"/measurements/{sid}/print?unc=full").text
    post(phys, "/uncertainty/settings", dict(modality="photon", back=page, u_s2_kq="0,35", d_s2_kq="0.6000"), page=page)
    post(phys, "/uncertainty/extra", dict(modality="photon", stage="2", name="Нестабильность выхода ускорителя", u_new="0,2",
                                          note="TG-51", back=page), page=page)
    full = phys.get(f"/measurements/{sid}/print?unc=full").text
    assert "изменено, по умолчанию 0,60" in full and "добавлено пользователем: TG-51" in full
    assert "Нестабильность выхода ускорителя" in full and "изменены пользователем: 2" in full
    assert "изменены пользователем: 2" in phys.get(f"/measurements/{sid}/print").text          # the short appendix says it too
    post(phys, "/uncertainty/settings/reset", dict(modality="photon", back=page), page=page)


# --------------------------------------------------------------------------- distributions and formulas
def test_standard_components_carry_distribution_and_formula():
    from core import uncertainty_distributions as ud
    for b in (uncertainty.photon_budget(), uncertainty.electron_budget(True, True, 1.5), uncertainty.electron_budget(False, False, 6.0)):
        for c in b.stage1 + b.stage2:
            assert c.dist in ud.DISTRIBUTIONS and len(c.how) > 20, c.code
    assert ud.standard_uncertainty("uniform", 2.0) == pytest.approx(1.1547, abs=1e-4)           # a / sqrt(3)
    assert ud.standard_uncertainty("triangular", 2.0) == pytest.approx(0.8165, abs=1e-4)        # a / sqrt(6)
    assert ud.standard_uncertainty("ushaped", 2.0) == pytest.approx(1.4142, abs=1e-4)           # a / sqrt(2)
    assert ud.standard_uncertainty("normal", 2.5, k=2) == pytest.approx(1.25)                   # U / k
    electron = uncertainty.electron_budget(True, True, 1.5)
    assert "McDermott" in next(c.how for c in electron.stage2 if c.code == "s2_kq")


def test_added_line_keeps_distribution_and_formula(world, client):
    phys, page = world["phys"], page_of(world)
    r = post(phys, "/uncertainty/extra", dict(modality="photon", stage="2", name="Установка глубины камеры", u_new="0,30", dist="uniform",
                                              how="u = c · a / √3", note="McDermott", back=page), page=page)
    assert r.status_code == 303
    assert q(client, "SELECT dist, how FROM uncertainty_settings WHERE is_extra AND active AND name='Установка глубины камеры'")[0] == ("uniform", "u = c · a / √3")
    html = phys.get(page).text
    assert "u = c · a / √3" in html and "Как получают стандартную неопределённость" in html and "McDermott 2024" in html
    assert post(phys, "/uncertainty/extra", dict(modality="photon", stage="2", name="Строка с ошибкой", u_new="0,1", dist="bogus"), page=page).status_code == 422
    post(phys, "/uncertainty/settings/reset", dict(modality="photon", back=page), page=page)
