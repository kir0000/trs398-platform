"""'Is there a newer version?': one request to the public release list of GitHub, only when somebody presses the button."""
from __future__ import annotations

import json
import re
import urllib.request

RELEASES = "https://api.github.com/repos/kir0000/trs398-platform/releases/latest"


def version_key(v: str) -> tuple:
    """2.0.0-rc2 < 2.0.0 < 2.0.1 (a release candidate precedes its release); leading 'v' and '+dev' are ignored."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?", v.strip())
    if not m:
        return (0, 0, 0, 0, 0)
    major, minor, patch, rc = m.groups()
    return (int(major), int(minor), int(patch), 0 if rc is not None else 1, int(rc or 0))


def check(current: str, fetch=None) -> dict:
    """{'ok': True, 'latest', 'url', 'newer'} or {'ok': False, 'error'}. `fetch` lets the tests avoid the network."""
    try:
        if fetch is None:
            req = urllib.request.Request(RELEASES, headers={"Accept": "application/vnd.github+json", "User-Agent": "trs398"})
            with urllib.request.urlopen(req, timeout=8) as r:       # noqa: S310 (a fixed https address)
                data = json.loads(r.read().decode("utf-8"))
        else:
            data = fetch()
        latest = str(data["tag_name"])
        return {"ok": True, "latest": latest, "url": data.get("html_url", ""), "newer": version_key(latest) > version_key(current)}
    except Exception as e:                                           # noqa: BLE001  (no network, rate limit, ...)
        return {"ok": False, "error": str(e)[:160]}
