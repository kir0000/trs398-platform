"""Terms: the international abbreviations (SSD, SAD, SCD) are used, not the Russian ones; the help has a glossary."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUSSIAN_ABBREVIATIONS = re.compile(r"РИ[ОПД]")           # three Russian abbreviations of the distances


def test_no_russian_abbreviations_of_the_distances_anywhere():
    files = [p for pattern in ("app/**/*.py", "app/templates/*.html", "core/*.py", "docs/*.md", "*.md", "tools/*.py", "app/i18n/en.json")
             for p in ROOT.glob(pattern)]
    bad = {str(p.relative_to(ROOT)): RUSSIAN_ABBREVIATIONS.findall(p.read_text(encoding="utf-8")) for p in files}
    assert not {k: v for k, v in bad.items() if v}, {k: v for k, v in bad.items() if v}


def test_the_help_has_a_glossary_in_both_languages():
    ru = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    en = (ROOT / "docs" / "USER_GUIDE.en.md").read_text(encoding="utf-8")
    assert "## 9. Глоссарий: термины и сокращения" in ru and "## 9. Glossary: terms and abbreviations" in en
    for term in ("SSD", "SAD", "SCD", "TMR", "PDD(", "CUSUM", "TRS-398", "FFF", "MU", "I-MR", "Western Electric"):
        assert term in ru.split("## 9. Глоссарий")[1] and term in en.split("## 9. Glossary")[1], term
    assert ru.count("\n| ") > 40 and en.count("\n| ") > 40                                # a table of terms, three groups
    assert ru.index("## 9. Глоссарий") < ru.index("## Важно") and en.index("## 9. Glossary") < en.index("## Important")


def test_the_pages_show_ssd_and_sad(world=None):
    sheet = (ROOT / "app" / "templates" / "form.html").read_text(encoding="utf-8")
    assert "'SSD', 'SSD'" in sheet or "RB('geometry', 'SSD', 'SSD'" in sheet
    assert "RB('geometry', 'SAD', 'SAD'" in sheet
