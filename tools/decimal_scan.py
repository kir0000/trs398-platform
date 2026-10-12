"""List decimal points that are shown to the user on the Russian pages (they must be commas there).

    .venv\\Scripts\\python tools/decimal_scan.py            # uses the test database like the tests do
It renders the pages of a database with demo data (the same list as tests/test_i18n.py) and prints, per page, the numbers
written with a point inside visible text and visible input values.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

POINT = re.compile(r"(?<![\w.,/])(\d+)\.(\d+)(?![\w/]|\.\d)")


def visible_points(html: str) -> list[str]:
    """Numbers with a decimal point in the text a person reads: text nodes (not scripts, styles, code) and visible input values."""
    html = re.sub(r"<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>|<pre\b.*?</pre>|<code\b.*?</code>", " ", html, flags=re.S | re.I)
    found = []
    for tag in re.findall(r"<input\b[^>]*>", html, flags=re.I):
        if re.search(r'type="hidden"', tag, flags=re.I):
            continue
        for attr in ("value", "placeholder"):
            m = re.search(attr + r'="([^"]*)"', tag)
            if m:
                found += [mm.group(0) for mm in POINT.finditer(m.group(1))]
    text = re.sub(r"<[^>]+>", "\x00", html)
    for node in text.split("\x00"):
        found += [mm.group(0) for mm in POINT.finditer(node)]
    return found
