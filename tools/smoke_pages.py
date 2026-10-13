"""Open every page of a running program and report errors: python tools/smoke_pages.py http://localhost:8100 login password
Reads only (the pages are GET); the measurement pages are taken from the list on /measurements. Exit code 1 if anything is wrong."""
import re
import sys

import httpx

base, login, password = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
c = httpx.Client(base_url=base, follow_redirects=True, timeout=120)
tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
r = c.post("/login", data={"login": login, "password": password, "csrf": tok})
assert "/login" not in str(r.url), "sign-in failed"
pages = ["/", "/measurements", "/measurements/new?modality=photon", "/measurements/new?modality=electron", "/trends",
         "/compare", "/uncertainty", "/equipment", "/help", "/admin/users", "/admin/backups", "/admin/purge", "/admin/audit", "/about", "/healthz"]
ids = re.findall(r'href="/measurements/(\d+)"', c.get("/measurements").text)
for sid in ids[:3] + ids[-2:]:
    pages += [f"/measurements/{sid}", f"/measurements/{sid}/print", f"/measurements/{sid}/pdf"]
bad = 0
for lang in ("ru", "en"):
    c.get(f"/lang/{lang}")
    for p in pages:
        r = c.get(p)
        text = r.text if "pdf" not in r.headers.get("content-type", "") else ""
        problem = (r.status_code >= 400 and f"HTTP {r.status_code}") or ("Traceback" in text and "traceback") or ""
        if "/pdf" in p and r.headers.get("content-type") != "application/pdf":
            problem = problem or f"not a pdf ({r.status_code})"
        if lang == "en":
            visible = re.sub(r"<(script|style).*?</>|<[^>]*>", "|", text, flags=re.S | re.I).replace("Расчёт", "")
            found = re.search(r".{0,30}[А-Яа-яЁё]{4,}.{0,20}", visible)
            if found:
                problem = problem or "Russian left in English: " + found.group(0).replace(chr(10), " ")
        if problem:
            bad += 1
            print(f"[{lang}] {p}: {problem}")
print(f"{len(pages) * 2} pages checked, {bad} problem(s)")
sys.exit(1 if bad else 0)
