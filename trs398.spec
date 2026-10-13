# PyInstaller: pyinstaller trs398.spec  ->  dist/TRS398/TRS398.exe (the folder is the portable build; the installer wraps it)
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("uvicorn") + collect_submodules("app") + collect_submodules("core") + ["restore", "verify_backup", "argon2", "multipart", "pystray._win32"]
datas = [("app/templates", "app/templates"), ("app/static", "app/static"), ("app/i18n", "app/i18n"),
         ("app/migrations", "app/migrations"), ("core/data", "core/data"), ("VERSION", "."), ("docs/USER_GUIDE.md", "docs"), ("docs/USER_GUIDE.en.md", "docs")]
a = Analysis(["tray.py"], pathex=[".", "tools"], hiddenimports=hidden, datas=datas,
             excludes=["tkinter", "matplotlib", "pytest", "psycopg", "weasyprint"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TRS398", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="TRS398")
