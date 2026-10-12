"""Collect the Russian phrases of the interface into the English catalog app/i18n/en.json.

    python tools/i18n_extract.py            # report: how many phrases, how many still need an English text
    python tools/i18n_extract.py --write    # add new phrases with an empty translation (they stay inactive until filled)
    python tools/i18n_extract.py --merge f.json   # take translations from f.json ({russian: english}) into the catalog
    python tools/i18n_extract.py --todo out.json  # write the untranslated phrases to out.json for translating

A phrase is a piece of text between tags or between dynamic values ({{ }}), so that numbers and names around it
do not matter. Strings of Python code and Jinja calls (Q('...')) are collected both as written and as the text nodes
that remain after the symbol markup (app/notation.py) has split them at <i>, <sub>, <sup>.
"""
from __future__ import annotations

import argparse
import ast
import glob
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.notation import sym                                                    # noqa: E402

CAT = ROOT / "app" / "i18n" / "en.json"
CYR = re.compile(r"[А-Яа-яЁё]")
WS = re.compile(r"\s+")
TAG = re.compile(r"<[^>]+>")
JINJA = re.compile(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", re.S)
JINJA_STR = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)\"""")
ATTR = re.compile(r'\b(?:title|placeholder|aria-label|alt)="([^"]*)"')
JS_STR = JINJA_STR


def norm(text: str) -> str:
    return WS.sub(" ", html.unescape(text)).strip()


def fragments_of_markup(markup: str) -> set[str]:
    """Russian runs of a piece of HTML-like text: split at tags."""
    out = set()
    for part in TAG.split(markup):
        part = norm(part)
        if CYR.search(part):
            out.add(part)
    return out


def with_symbols(text: str) -> set[str]:
    """The text as written, and as it is split after sym() has marked up the quantity symbols."""
    out = set()
    for source in (text, str(sym(text))):
        if "<" in source or '="' in source:                    # a piece of markup from an f-string: attribute values, then text between tags
            for value in ATTR.findall(source):
                if CYR.search(value):
                    out.add(norm(value))
            source = re.sub(r"[\w-]+=\"[^\"]*\"", " ", source)
            source = source.replace('"', " ")
            out |= fragments_of_markup(source)
        else:
            plain = norm(source)
            if CYR.search(plain):
                out.add(plain)
    return out


def from_template(path: Path) -> set[str]:
    out: set[str] = set()
    src = path.read_text(encoding="utf-8")
    # JS and CSS: string literals only
    for m in re.finditer(r"<script\b.*?</script>", src, re.S | re.I):
        for s in JS_STR.finditer(m.group(0)):
            raw = s.group(1) if s.group(1) is not None else s.group(2)
            if CYR.search(raw):
                out |= with_symbols(raw.replace("\\'", "'"))
    src = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", "", src, flags=re.S | re.I)
    # string literals inside Jinja ({{ Q('...') }}, {{ 'a' if x else 'b' }}, {% set %}), then the static text around them
    for m in JINJA.finditer(src):
        for s in JINJA_STR.finditer(m.group(0)):
            raw = s.group(1) if s.group(1) is not None else s.group(2)
            if CYR.search(raw):
                out |= with_symbols(raw.replace("\\'", "'"))
    # {% filter sym %}...{% endfilter %}: text that the symbol markup splits at <i>, <sub>, <sup>
    for block in re.finditer(r"\{%\s*filter sym\s*%\}(.*?)\{%\s*endfilter\s*%\}", src, re.S):
        for part in JINJA.split(block.group(1)):
            if CYR.search(part):
                out |= with_symbols(part)
    static = JINJA.sub("\x01", src)
    for attr in ATTR.findall(static):
        for part in attr.split("\x01"):
            if CYR.search(part):
                out.add(norm(part))
    for part in re.split(r"\x01", TAG_SPLIT.sub("\x01", static)):
        part = norm(part)
        if CYR.search(part):
            out.add(part)
    return out


TAG_SPLIT = re.compile(r"<[^>]+>")


def from_python(path: Path) -> set[str]:
    out: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                skip.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip and CYR.search(node.value):
            out |= with_symbols(node.value)
    return out


LOGIC_WORDS = {"ДЕЙ", "ПН", "вод", "наб"}        # compared with data in templates/scripts: they must stay Russian


def is_logic(phrase: str) -> bool:
    """Strings that are code, not interface text: regular expressions, markup pieces of f-strings, words used in conditions."""
    return (phrase in LOGIC_WORDS or '="' in phrase or "(?" in phrase or "[А-Яа-яЁё]" in phrase
            or (phrase.startswith(")") and ">" in phrase))


def from_data(path: Path) -> set[str]:
    """Russian words of the reference data that appear on pages: chamber names and wall materials."""
    out: set[str] = set()
    for chamber in json.loads(path.read_text(encoding="utf-8")).get("chambers", []):
        for key in ("name", "wall_material"):
            value = chamber.get(key) or ""
            for part in re.split(r"[()/]", value):
                part = norm(part)
                if CYR.search(part):
                    out.add(part)
            if CYR.search(value):
                out.add(norm(value))
    return out


def collect() -> set[str]:
    found: set[str] = set()
    for f in glob.glob(str(ROOT / "app" / "templates" / "*.html")):
        found |= from_template(Path(f))
    for f in glob.glob(str(ROOT / "core" / "data" / "*.json")):
        found |= from_data(Path(f))
    for pattern in ("app/*.py", "core/*.py"):
        for f in glob.glob(str(ROOT / pattern)):
            if Path(f).name == "notation.py":
                continue
            found |= from_python(Path(f))
    return {s for s in found if CYR.search(s) and not is_logic(s)}


def load() -> dict[str, str]:
    return json.loads(CAT.read_text(encoding="utf-8")) if CAT.exists() else {}


def save(cat: dict[str, str]) -> None:
    CAT.parent.mkdir(exist_ok=True)
    lines = [f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}" for k, v in sorted(cat.items())]
    CAT.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--merge")
    ap.add_argument("--todo")
    ap.add_argument("--numbered", help="write the untranslated phrases as numbered lines to this text file")
    ap.add_argument("--merge-numbered", nargs=2, metavar=("TODO_JSON", "TRANSLATIONS_JSON"),
                    help="TRANSLATIONS_JSON is {number: english}; numbers refer to the order of TODO_JSON")
    a = ap.parse_args()
    cat = load()
    if a.merge:
        add = json.loads(Path(a.merge).read_text(encoding="utf-8"))
        cat.update({norm(k): v for k, v in add.items() if v})
        save(cat)
        print(f"merged {len(add)} entries; catalog has {len(cat)}")
        return
    if a.merge_numbered:
        keys = list(json.loads(Path(a.merge_numbered[0]).read_text(encoding="utf-8")))
        tr = json.loads(Path(a.merge_numbered[1]).read_text(encoding="utf-8"))
        bad = [n for n in tr if not n.isdigit() or int(n) >= len(keys)]
        assert not bad, f"unknown numbers: {bad}"
        cat.update({keys[int(n)]: v for n, v in tr.items() if v})
        save(cat)
        print(f"merged {len(tr)} entries; catalog has {len(cat)}")
        return
    found = collect()
    cat_norm = {norm(k): v for k, v in cat.items()}
    missing = sorted(s for s in found if not cat_norm.get(s))
    print(f"phrases found: {len(found)}, translated: {len(found) - len(missing)}, to translate: {len(missing)}")
    if a.write:
        for s in missing:
            cat.setdefault(s, "")
        save(cat)
        print("catalog updated:", CAT)
    if a.numbered:
        Path(a.numbered).write_text("\n".join(f"{i}\t{s}" for i, s in enumerate(missing)), encoding="utf-8")
        Path(a.numbered).with_suffix(".json").write_text(json.dumps({s: "" for s in missing}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("numbered list written to", a.numbered)
    if a.todo:
        Path(a.todo).write_text(json.dumps({s: "" for s in missing}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("to translate written to", a.todo)


if __name__ == "__main__":
    main()
