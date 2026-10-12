"""Typography of quantity symbols (TRS-398 Rev.1 style): italic symbols, upright descriptive subscripts."""
import re
from pathlib import Path

import pytest

from app.notation import sym, sym_plain

CASES = [
    ("kQ,Q0", "<i>k</i><sub><i>Q</i>,<i>Q</i><sub>0</sub></sub>"),
    ("kQ,Qo", "<i>k</i><sub><i>Q</i>,<i>Q</i><sub>0</sub></sub>"),
    ("kQ,Qint", "<i>k</i><sub><i>Q</i>,<i>Q</i><sub>int</sub></sub>"),
    ("ND,w,Q0", "<i>N</i><sub><i>D</i>,w,<i>Q</i><sub>0</sub></sub>"),
    ("Dw,Q", "<i>D</i><sub>w,<i>Q</i></sub>"),
    ("Dw(zmax)", "<i>D</i><sub>w</sub>(<i>z</i><sub>max</sub>)"),
    ("kTP", "<i>k</i><sub>TP</sub>"),
    ("kelec", "<i>k</i><sub>elec</sub>"),
    ("kpol", "<i>k</i><sub>pol</sub>"),
    ("ks", "<i>k</i><sub>s</sub>"),
    ("kvol", "<i>k</i><sub>vol</sub>"),
    ("TPR20,10", "<i>TPR</i><sub>20,10</sub>"),
    ("R50,w", "<i>R</i><sub>50,w</sub>"),
    ("zref", "<i>z</i><sub>ref</sub>"),
    ("M+", "<i>M</i><sub>+</sub>"),
    ("M−", "<i>M</i><sub>−</sub>"),
    ("uc", "<i>u</i><sub>c</sub>"),
    ("U (k=2)", "<i>U</i> (<i>k</i> = 2)"),
    ("⁶⁰Co", "<sup>60</sup>Co"),
    ("Co-60", "<sup>60</sup>Co"),
    ("г/см²", "г см<sup>−2</sup>"),
    ("(2M)", "(2<i>M</i>)"),
    ("ki", "<i>k</i><sub><i>i</i></sub>"),
    ("uA²", "<i>u</i><sub>A</sub>²"),
]


@pytest.mark.parametrize("plain,html", CASES)
def test_symbols(plain, html):
    assert str(sym(plain)) == html


def test_words_and_units_are_left_alone():
    for text in ("PTW UNIDOS", "MU", "MV", "MeV", "Гр/MU", "нКл/MU", "SSD", "TRS-398 Rev.1"):
        assert str(sym(text)) == text


def test_text_is_escaped_before_markup_is_added():
    assert str(sym("R50 < 2 <script>")) == "<i>R</i><sub>50</sub> &lt; 2 &lt;script&gt;"
    assert sym_plain("kQ,Q0 R50 < 2") == "kQ,Q0 R50 < 2"


def test_templates_use_one_convention():
    """Descriptive subscripts upright, Q and D italic; no italic parentheses in the kTP formula."""
    root = Path(__file__).resolve().parent.parent
    bad = []
    for f in list((root / "app" / "templates").glob("*.html")) + [root / "app" / "protocol.py"]:
        text = f.read_text(encoding="utf-8")
        for pattern in (r"<sub><i>(?:ref|max|T,P|w,Q)</i></sub>", r"<i>\(</i>", r"<i>[TP]\)</i>"):
            bad += [f"{f.name}: {m.group(0)}" for m in re.finditer(pattern, text)]
    assert not bad, bad

