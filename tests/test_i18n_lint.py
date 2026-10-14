"""Automatic checks of the translations: the engine at the edges of a phrase, the hygiene of the catalog, glued variables in
the templates, and every status of a record on every page for every role in English (this class of bugs showed up only in use)."""
import glob
import re
import sys
from pathlib import Path

import pytest

from app import i18n
from tests.test_app import client, create_measurement, post, q, world  # noqa: F401  (fixtures are discovered here)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import i18n_extract  # noqa: E402

ALLOWED = {"Language / Язык"} | i18n_extract.LOGIC_WORDS
CYR = r"[А-Яа-яЁё]"


# --------------------------------------------------------------------------- the engine at the edges of a phrase
def test_a_phrase_with_a_punctuation_edge_translates_next_to_a_russian_variable():
    html = '<p>НЕ УТВЕРЖДЕНО: статус «черновик». Документ предварительный.</p>'
    out = i18n.translate_html(html, "en", False)
    assert "NOT APPROVED" in out and "draft" in out and "preliminary" in out and "УТВЕРЖДЕНО" not in out


def test_a_phrase_never_matches_inside_a_longer_russian_word():
    cat = i18n.catalog()
    word = next(k for k in cat if re.fullmatch(CYR + r"{4,8}", k))                 # a single-word phrase
    for inside in (f"{word}ов", f"пере{word}", f"{word}-физик"):
        assert i18n.translate_plain(inside) == inside, inside


# --------------------------------------------------------------------------- the catalog
def test_catalog_entries_are_clean():
    import json
    entries = json.loads(i18n.CATALOG_FILE.read_text(encoding="utf-8"))
    problems, seen = [], {}
    for k, v in entries.items():
        norm = re.sub(r"\s+", " ", k.strip())
        if norm in seen and seen[norm][1] != v:
            problems.append(f"the same phrase twice with different translations: {norm[:50]!r}")
        seen[norm] = (k, v)
        if not v or not v.strip():
            problems.append(f"empty translation: {k[:50]!r}")
        elif re.search(CYR, v) and k not in ALLOWED:
            problems.append(f"Russian letters in the English text: {k[:40]!r} -> {v[:40]!r}")
        # numbers, percent signs and format placeholders must survive the translation
        for token in set(re.findall(r"\d+(?:[.,]\d+)?|%[sd]|\{[^}]*\}", k)):
            if token.replace(",", ".") not in v.replace(",", "."):
                problems.append(f"{token!r} of {k[:40]!r} is missing in the translation {v[:40]!r}")
    assert not problems, chr(10).join(problems[:25])


# --------------------------------------------------------------------------- the templates
def test_no_russian_word_is_glued_to_a_variable_in_the_templates():
    """слово{{ x }} or {{ x }}слово cannot be translated: a fragment of a word is not a phrase."""
    rx = re.compile(CYR + r"\{\{|\}\}" + CYR)
    safe = ("{{ 'в воде ' }}на референсной", "'в воде ' }}на референсной")        # the value ends with a space
    bad = []
    for f in sorted(glob.glob(str(ROOT / "app" / "templates" / "*.html"))):
        text = Path(f).read_text(encoding="utf-8")
        for m in rx.finditer(text):
            if any(x in text[max(0, m.start() - 30):m.end() + 30] for x in safe):
                continue
            bad.append(f"{Path(f).name}: {text[max(0, m.start() - 25):m.end() + 25]!r}")
    assert not bad, "\n".join(bad)


# --------------------------------------------------------------------------- every status, every role, in English
def record(world_, state):
    sid = int(create_measurement(world_, "phys").headers["location"].rsplit("/", 1)[1])
    page = f"/measurements/{sid}"
    if state in ("submitted", "approved", "returned", "voided"):
        assert post(world_["phys"], f"{page}/submit", page=page).status_code == 303
    if state in ("approved", "voided"):
        assert post(world_["rev"], f"{page}/approve", {"comment": "ok"}, page=page).status_code == 303
    if state == "returned":
        assert post(world_["rev"], f"{page}/return", {"comment": "check the pressure"}, page=page).status_code == 303
    if state == "voided":
        assert post(world_["adm"], f"{page}/void", {"reason": "entered by mistake"}, page=page).status_code == 303
    return sid


def test_every_status_of_a_record_on_every_page_for_every_role_has_no_russian_left(world, client):
    sids = {state: record(world, state) for state in ("draft", "submitted", "returned", "approved", "voided")}
    bad = {}
    checked = 0
    for who in ("adm", "phys", "rev", "view"):
        s = world[who]
        s.get("/lang/en")
        for state, sid in sids.items():
            for suffix in ("", "/print", "/print?unc=full", "/edit"):
                url = f"/measurements/{sid}{suffix}"
                r = s.get(url)
                assert r.status_code in (200, 403, 404), (who, url, r.status_code)
                checked += 1
                left = [t for t in i18n.leftovers(r.text) if t not in ALLOWED]
                if left:
                    bad[f"{who} {url} ({state})"] = left[:5]
        for url in ("/measurements", "/measurements?status=draft", "/measurements?status=submitted", "/about", "/help", "/trends", "/compare",
                    "/uncertainty", "/equipment", "/equipment?tab=dosimeters", "/measurements/new?modality=photon",
                    "/admin/users", "/admin/backups", "/admin/purge", "/admin/audit", "/admin/audit/clear", "/admin/settings", "/nonexistent"):
            r = s.get(url)
            checked += 1
            left = [t for t in i18n.leftovers(r.text) if t not in ALLOWED]
            if left:
                bad[f"{who} {url}"] = left[:5]
    assert checked > 100
    assert not bad, "\n".join(f"{k}: {v}" for k, v in list(bad.items())[:15])


def test_text_typed_by_people_is_left_as_written_in_a_translate_no_element():
    html = '<td><b>Причина:</b> <span translate="no">введено по ошибке <i>и</i></span></td><td>введено по ошибке</td>'
    out = i18n.translate_html(html, "en", False)
    assert '<span translate="no">введено по ошибке <i>и</i></span>' in out                  # not even a nested tag is touched
    assert "Reason:" in out and "entered by" in out.split("</span>")[-1]                     # the rest of the page is translated
    assert i18n.leftovers(out) == [t for t in i18n.leftovers(out) if "введено" not in t or "entered by" in t]
    assert i18n.translate_html(html, "ru", False) == html


def test_the_extractor_reads_every_python_package_with_interface_texts():
    """A new package of the web side (app/routes) must not drop out of the translation check silently."""
    source = (ROOT / "tools" / "i18n_extract.py").read_text(encoding="utf-8")
    for package in sorted(p.name for p in (ROOT / "app").iterdir() if p.is_dir() and (p / "__init__.py").exists()):
        assert f"app/{package}/*.py" in source, f"tools/i18n_extract.py does not read app/{package}"
