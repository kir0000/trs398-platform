"""Typography of quantity symbols as in IAEA TRS-398 Rev.1: italic quantity symbols, upright descriptive
subscripts (w, ref, max, pol, elec, TP, vol, c, pl), italic quality index Q with a subscript 0, superscripts for
the nuclide (60Co) and for powers of units (g cm-2).

`sym(text)` takes plain text such as "kQ,Q0 = f(TPR20,10)", escapes it and returns HTML with <i>, <sub>, <sup>.
It is used as the Jinja filter `sym` for every label, hint and note that is typed as plain text, and it is
also valid inside Plotly titles.
"""
from __future__ import annotations

import re
from html import escape

from markupsafe import Markup


def _i(t: str) -> str:
    return f"<i>{t}</i>"


def _sub(t: str) -> str:
    return f"<sub>{t}</sub>"


Q0 = _i("Q") + _sub("0")
KQ = _i("k") + _sub(_i("Q") + "," + _i("Q") + _sub("0"))
_DW = _i("D") + _sub("w")
_ND = _i("N") + _sub(_i("D") + ",w")


def _z(idx: str) -> str:
    return _i("z") + _sub(idx)


# (pattern, replacement) pairs; alternatives are tried in order, the most specific first.
_RULES: list[tuple[str, str]] = [
    (r"ND,w,Q[0oо]", _i("N") + _sub(_i("D") + ",w," + Q0)),
    (r"ND,w,Co", _i("N") + _sub(_i("D") + ",w,Co")),
    (r"ND,w", _ND),
    (r"Dw,Q", _i("D") + _sub("w," + _i("Q"))),
    (r"Dw\(zref\)", _DW + "(" + _z("ref") + ")"),
    (r"Dw\(zmax\)", _DW + "(" + _z("max") + ")"),
    (r"Dw", _DW),
    (r"kQ,Qint", _i("k") + _sub(_i("Q") + "," + _i("Q") + _sub("int"))),
    (r"kQ,Q[0oо]", KQ),
    (r"kQ", KQ),
    (r"kpol\(Q[0oо]\)", _i("k") + _sub("pol") + "(" + Q0 + ")"),
    (r"kTP", _i("k") + _sub("TP")),
    (r"kelec", _i("k") + _sub("elec")),
    (r"kpol", _i("k") + _sub("pol")),
    (r"kvol", _i("k") + _sub("vol")),
    (r"ks", _i("k") + _sub("s")),
    (r"MQ", _i("M") + _sub(_i("Q"))),
    (r"ki", _i("k") + _sub(_i("i"))),
    (r"M[+−]", None),                       # handled in code: M with sign subscript
    (r"M[12]", None),
    (r"TPR20,10", _i("TPR") + _sub("20,10")),
    (r"R50,w", _i("R") + _sub("50,w")),
    (r"R50", _i("R") + _sub("50")),
    (r"zref,w", _z("ref,w")),
    (r"zref,pl", _z("ref,pl")),
    (r"zref", _z("ref")),
    (r"zmax", _z("max")),
    (r"cpl", _i("c") + _sub("pl")),
    (r"hpl", _i("h") + _sub("pl")),
    (r"a[012]", None),
    (r"V[12]", None),
    (r"[PT]0", None),
    (r"Uотн", _i("U") + _sub("отн")),
    (r"u[12cAB]", None),
    (r"k ?= ?2(?!\d)", _i("k") + " = 2"),
    (r"Q[0oо]", Q0),
    (r"Q", _i("Q")),
    (r"(?:⁶⁰|60)Co", "<sup>60</sup>Co"),
    (r"Co-60", "<sup>60</sup>Co"),
    (r"г/см[²2]", "г см<sup>−2</sup>"),
    (r"см[²2]", "см<sup>2</sup>"),
    (r"(?:PDD|TMR)", None),
    (r"[TPLUM]", None),
]

_L = "A-Za-zА-Яа-яЁё_"          # letters only: a digit before ("2M") or a superscript after ("u1²") does not glue a symbol
_PATTERN = re.compile(rf"(?<![{_L}])(?:" + "|".join(f"(?P<g{n}>{p})" for n, (p, _) in enumerate(_RULES)) + rf")(?![{_L}0-9])")


def _convert(m: re.Match) -> str:
    n = int(m.lastgroup[1:])
    text = m.group(0)
    repl = _RULES[n][1]
    if repl is not None:
        return repl
    if text[0] == "M" and len(text) == 2:                 # M+, M−, M1, M2
        return _i("M") + _sub(text[1])
    if text[0] in "aVuPT" and len(text) == 2:             # a0, V1, u1, uc, P0, T0
        return _i(text[0]) + _sub(text[1])
    return _i(text)                                       # PDD, TMR, lone T, P, L, U


def sym(text) -> Markup:
    s = escape("" if text is None else str(text))
    # The escape turns "<" into "&lt;": the regexes above never contain those characters.
    return Markup(_PATTERN.sub(_convert, s))


def sym_plain(text) -> str:
    """The same text without markup (for title attributes and file names)."""
    return re.sub(r"<[^>]+>", "", str(sym(text)).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
