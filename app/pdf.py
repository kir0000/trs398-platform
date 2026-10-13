"""HTML to PDF with the browser that is already on the computer (Microsoft Edge on Windows 10/11, else Chrome/Chromium)
in its headless mode; WeasyPrint is used only if no browser is found and the package happens to be installed."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_CANDIDATES = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)


class PdfUnavailable(Exception):
    pass


def find_browser() -> str | None:
    env = os.environ.get("TRS_BROWSER")
    if env and Path(env).is_file():
        return env
    for c in _CANDIDATES:
        p = os.path.expandvars(c)
        if Path(p).is_file():
            return p
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def html_to_pdf(html: str, timeout: int = 60) -> bytes:
    browser = find_browser()
    if browser:
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "protocol.html", Path(tmp) / "protocol.pdf"
            src.write_text(html, encoding="utf-8")
            cmd = [browser, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                   f"--user-data-dir={Path(tmp) / 'profile'}", f"--print-to-pdf={out}", src.as_uri()]
            try:
                subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if out.is_file() and out.stat().st_size > 0:
                return out.read_bytes()
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        raise PdfUnavailable from None
    return HTML(string=html).write_pdf()
