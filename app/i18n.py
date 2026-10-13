"""Two interface languages (Russian is the source language, English is added from a phrase catalog).

Pages are written in Russian. For English the finished HTML is translated phrase by phrase: the catalog
`app/i18n/en.json` maps a Russian phrase to its English text; text nodes, a few attributes (title, placeholder, aria-label,
alt, data-help) and the string literals inside <script> are translated, longest phrase first, so that dynamic parts
(numbers, names, dates) around the phrases stay as they are. Values that the server reads back (value="...", form field
names, option values) are never translated.

Language choice, in this order: ?lang=xx of the request (used for printing/PDF), the session, the cookie `lang`,
the environment variable TRS_LANG, Russian.
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

LANGS = ("ru", "en")
CATALOG_FILE = Path(__file__).resolve().parent / "i18n" / "en.json"
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"(<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)", re.S | re.I)
_ATTR = re.compile(r'\b(title|placeholder|aria-label|alt|data-help)="([^"]*)"')
_VALUE = re.compile(r'\bvalue="([\d\s,.\-+−]*)"')
_JS_STRING = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)\"""")


def default_lang() -> str:
    """TRS_LANG, else the language of the settings file, else Russian."""
    code = os.environ.get("TRS_LANG", "").strip().lower()
    if not code:
        try:
            from app import settings
            code = str(settings.load().get("language", "ru")).strip().lower()
        except Exception:                                    # noqa: BLE001  (a damaged file must not break the pages)
            code = "ru"
    return code if code in LANGS else "ru"


@lru_cache(maxsize=1)
def catalog() -> dict[str, str]:
    """{russian phrase: english phrase}; entries with an empty translation are ignored."""
    if not CATALOG_FILE.exists():
        return {}
    raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    return {_WS.sub(" ", k.strip()): v.strip() for k, v in raw.items() if v and v.strip()}


_LETTER = re.compile(r"[А-Яа-яЁё]")


def _key_pattern(key: str) -> str:
    """The regular expression of one phrase. A phrase never matches inside a longer Russian word, but that matters only at its
    own edges that are letters: a phrase that ends with a quote or a bracket may stand right before a variable that starts
    with a Russian letter (статус «{{ название }}»). The same for a hyphenated Russian compound (Демо-физик)."""
    head = r"(?<![А-Яа-яЁё])(?<![А-Яа-яЁё]-)" if _LETTER.match(key[0]) else ""
    tail = r"(?![А-Яа-яЁё])(?!-[А-Яа-яЁё])" if _LETTER.match(key[-1]) else ""
    return head + re.escape(key) + tail


@lru_cache(maxsize=1)
def _matcher() -> re.Pattern | None:
    keys = sorted(catalog(), key=len, reverse=True)
    if not keys:
        return None
    return re.compile("|".join(_key_pattern(k) for k in keys))


def reload() -> None:
    catalog.cache_clear()
    _matcher.cache_clear()


def translate_plain(text: str) -> str:
    """Translate a plain (already unescaped) string; the text without Russian letters is returned unchanged."""
    if not CYRILLIC.search(text):
        return text
    m = _matcher()
    if not m:
        return text
    cat = catalog()
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    body = _WS.sub(" ", text.strip())
    return lead + m.sub(lambda mo: cat[mo.group(0)], body) + trail


def decimal_dot(text: str) -> str:
    """1,5 -> 1.5 for English; the quality index TPR20,10 is a name, not a number."""
    text = text.replace("20,10", "20\x00,10")
    return re.sub(r"(?<=\d),(?=\d)", ".", text).replace("\x00", "")


_POINT = re.compile(r"(?<![A-Za-z0-9_.,/])(\d+)\.(\d+)(?!\d)(?![/_]|\.\d)")


def decimal_comma(text: str) -> str:
    """0.18 -> 0,18 for Russian; dates (15.09.2026), addresses (192.168.1.20), versions (v2.0) and DOIs are not numbers."""
    return _POINT.sub(lambda m: m.group(1) + "," + m.group(2), text)


def _localize_ru(html: str, whole_page: bool = True) -> str:
    """Russian pages: a comma wherever a person reads a decimal number (text, visible inputs, titles); scripts, styles,
    code samples, links and the values that scripts and the server read back (hidden fields, data-*, option values) are left alone."""
    out = []
    code_depth = 0
    for token in _TOKEN.split(html):
        if not token:
            continue
        low = token[:7].lower()
        if token.startswith("<!--") or low.startswith("<style") or low.startswith("<script"):
            out.append(token)
        elif token.startswith("<"):
            name = re.match(r"</?\s*([a-zA-Z0-9]+)", token)
            tag_name = name.group(1).lower() if name else ""
            if tag_name in ("code", "pre"):
                code_depth = max(0, code_depth + (-1 if token.startswith("</") else 1))
            tag = token
            if tag_name == "input" and not re.search(r'type="hidden"', tag, re.I):
                tag = _VALUE.sub(lambda m: f'value="{decimal_comma(m.group(1))}"', tag)
            tag = re.sub(r'\b(placeholder|title|aria-label|alt)="([^"]*)"',
                         lambda m: f'{m.group(1)}="{htmllib.escape(decimal_comma(htmllib.unescape(m.group(2))), quote=True)}"', tag)
            tag = re.sub(r'\bdata-help="([^"]*)"',
                         lambda m: 'data-help="' + htmllib.escape(_localize_ru(htmllib.unescape(m.group(1)), whole_page=False), quote=True) + '"', tag)
            out.append(tag)
        elif code_depth:
            out.append(token)
        else:
            plain = htmllib.unescape(token)
            conv = decimal_comma(plain)
            out.append(token if conv == plain else htmllib.escape(conv, quote=False))
    return "".join(out)


def _translate_text_node(text: str, lang: str, in_index: bool) -> str:
    plain = htmllib.unescape(text)
    out = translate_plain(plain)
    if lang == "en" and not in_index:
        out = decimal_dot(out)
    return text if out == plain else htmllib.escape(out, quote=False)


def _translate_attr_value(name: str, value: str, lang: str) -> str:
    if name == "data-help":                                  # escaped HTML with markup of symbols
        return htmllib.escape(translate_html(htmllib.unescape(value), lang, whole_page=False), quote=True)
    plain = htmllib.unescape(value)
    out = translate_plain(plain)
    return value if out == plain else htmllib.escape(out, quote=True)


_CSS_STRING = re.compile(r'"([^"\n]*[А-Яа-яЁё][^"\n]*)"')
_HANDLER = re.compile(r'\b(on(?:submit|click|change))="([^"]*)"')


def _translate_handler(m: re.Match) -> str:
    """The texts of confirm('...') in an event attribute."""
    code = htmllib.unescape(m.group(2))
    out = _JS_STRING.sub(_js_literal, code)
    return m.group(0) if out == code else f'{m.group(1)}="{htmllib.escape(out, quote=True)}"'


def _translate_tag(tag: str, lang: str) -> str:
    tag = _HANDLER.sub(_translate_handler, tag)
    tag = _ATTR.sub(lambda m: f'{m.group(1)}="{_translate_attr_value(m.group(1), m.group(2), lang)}"', tag)
    if lang == "en" and tag[:6].lower() == "<input":
        tag = _VALUE.sub(lambda m: f'value="{decimal_dot(m.group(1))}"', tag)
    return tag


def _js_literal(m: re.Match) -> str:
    quote = "'" if m.group(1) is not None else '"'
    raw = m.group(1) if m.group(1) is not None else m.group(2)
    if not (CYRILLIC.search(raw) or "\\u04" in raw):
        return m.group(0)
    try:                                                     # JSON-style \u escapes (from |tojson) and plain JS escapes
        text = json.loads('"' + raw.replace('\\\'', "'").replace('"', '\\"') + '"') if quote == "'" else json.loads('"' + raw + '"')
    except ValueError:
        text = raw
    out = translate_plain(text)
    if out == text:
        return m.group(0)
    body = json.dumps(out, ensure_ascii=False)[1:-1]         # a JSON string body is a valid JS string body
    if quote == "'":
        body = body.replace('\\"', '"').replace("'", "\\'")
    return quote + body + quote


def _translate_script(script: str, lang: str) -> str:
    open_end = script.index(">") + 1
    head, body, tail = script[:open_end], script[open_end:-len("</script>")], script[-len("</script>"):]
    body = _JS_STRING.sub(_js_literal, body)
    if lang == "en":
        body = body.replace(".replace('.', ',')", ".replace(',', '.')")      # display helper of the entry form: decimal point
    return head + body + tail


class _NoTranslate:
    """Follows the elements marked translate="no" (texts typed by people: reasons, comments); their content is left as written."""

    def __init__(self):
        self.tag = None
        self.depth = 0

    def feed(self, token: str) -> None:
        m = re.match(r"<(/?)\s*([a-zA-Z0-9]+)([^>]*)>", token)
        if not m or token.endswith("/>"):
            return
        closing, name, rest = m.group(1) == "/", m.group(2).lower(), m.group(3)
        if self.tag is None:
            if not closing and re.search(r'translate\s*=\s*"no"', rest):
                self.tag, self.depth = name, 1
        elif name == self.tag:
            self.depth += -1 if closing else 1
            if self.depth == 0:
                self.tag = None

    @property
    def on(self) -> bool:
        return self.tag is not None


def translate_html(html: str, lang: str, whole_page: bool = True) -> str:
    """The page in the chosen language (Russian pages are returned untouched)."""
    if lang != "en":
        return _localize_ru(html, whole_page)
    out = []
    keep = _NoTranslate()
    index_depth = 0                                           # inside <sub>/<sup>: names such as 20,10 keep their comma
    code_depth = 0                                            # inside <code>/<pre>: examples are shown as written
    for token in _TOKEN.split(html):
        if not token:
            continue
        low = token[:7].lower()
        if token.startswith("<!--"):
            out.append(token)
        elif low.startswith("<style"):                       # the strings of the style sheet (the page footer of the PDF)
            out.append(_CSS_STRING.sub(lambda m: '"' + translate_plain(m.group(1)) + '"', token))
        elif low.startswith("<script"):
            out.append(_translate_script(token, lang))
        elif token.startswith("<"):
            keep.feed(token)
            name = re.match(r"</?\s*([a-zA-Z0-9]+)", token)
            if name and name.group(1).lower() in ("sub", "sup"):
                index_depth = max(0, index_depth + (-1 if token.startswith("</") else 1))
            if name and name.group(1).lower() in ("code", "pre"):
                code_depth = max(0, code_depth + (-1 if token.startswith("</") else 1))
            out.append(_translate_tag(token, lang))
        elif keep.on:
            out.append(token)
        else:
            out.append(_translate_text_node(token, lang, index_depth > 0 or code_depth > 0))
    result = "".join(out)
    if whole_page:
        result = result.replace('<html lang="ru">', '<html lang="en">', 1)
    return result


def leftovers(html: str) -> list[str]:
    """Russian fragments that are still on a page after translation (for the coverage test)."""
    found = []
    keep = _NoTranslate()
    for token in _TOKEN.split(html):
        if not token or token.startswith("<!--") or token[:6].lower() == "<style":
            continue
        if token.startswith("<") and not token[:7].lower().startswith("<script"):
            keep.feed(token)
        elif keep.on:
            continue
        if token[:7].lower().startswith("<script"):
            body = token[token.index(">") + 1:-len("</script>")]
            for m in _JS_STRING.finditer(body):
                raw = m.group(1) if m.group(1) is not None else m.group(2)
                if CYRILLIC.search(raw) or "\\u04" in raw:
                    try:
                        text = json.loads('"' + raw.replace('\\\'', "'").replace('"', '\\"') + '"')
                    except ValueError:
                        text = raw
                    if CYRILLIC.search(text):
                        found.append(text)
        elif token.startswith("<"):
            for name, value in _ATTR.findall(token):
                plain = htmllib.unescape(value)
                if name == "data-help":
                    found += leftovers(plain)
                elif CYRILLIC.search(plain):
                    found.append(plain)
        else:
            plain = htmllib.unescape(token)
            if CYRILLIC.search(plain):
                found.append(_WS.sub(" ", plain.strip()))
    return found
