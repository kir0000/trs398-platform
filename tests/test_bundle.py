"""The build (trs398.spec) must carry every data file the program reads at run time."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_spec_lists_existing_files_and_the_guide():
    spec = (ROOT / "trs398.spec").read_text(encoding="utf-8")
    sources = re.findall(r'\("([^"]+)", "[^"]+"\)', spec)
    assert sources and all((ROOT / s).exists() for s in sources), [s for s in sources if not (ROOT / s).exists()]
    assert "docs/USER_GUIDE.md" in sources and "docs/USER_GUIDE.en.md" in sources       # the Help page reads them
