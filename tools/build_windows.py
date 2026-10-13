"""Build the Windows editions:  python tools/build_windows.py [--installer]

  build/TRS398-portable-<version>.zip   unpack anywhere and run TRS398.exe (the data are kept in the folder `data` beside it)
  build/TRS398-setup-<version>.exe      the installer (needs Inno Setup 6: ISCC.exe on PATH or in Program Files)
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def iscc() -> str | None:
    found = shutil.which("ISCC")
    if found:
        return found
    for base in (r"C:\Program Files (x86)\Inno Setup 6", r"C:\Program Files\Inno Setup 6", str(Path.home() / "AppData/Local/Programs/Inno Setup 6")):
        if (Path(base) / "ISCC.exe").exists():
            return str(Path(base) / "ISCC.exe")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", action="store_true")
    a = ap.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build = ROOT / "build"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(build / "dist"),
                    "--workpath", str(build / "work"), "trs398.spec"], cwd=ROOT, check=True)
    folder = build / "dist" / "TRS398"
    portable = build / "portable" / "TRS398"
    shutil.rmtree(build / "portable", ignore_errors=True)
    shutil.copytree(folder, portable)
    (portable / "portable.flag").write_text("data are kept in the folder `data` next to this file\n", encoding="utf-8")
    zip_path = shutil.make_archive(str(build / f"TRS398-portable-{version}"), "zip", build / "portable")
    print("portable:", zip_path)
    if a.installer:
        exe = iscc()
        if not exe:
            raise SystemExit("Inno Setup 6 not found (ISCC.exe)")
        subprocess.run([exe, f"/DAppVersion={version}", str(ROOT / "installer" / "trs398.iss")], check=True)
        print("installer:", build / f"TRS398-setup-{version}.exe")


if __name__ == "__main__":
    main()
