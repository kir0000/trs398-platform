# PyInstaller: pyinstaller trs398.spec  ->  dist/TRS398/TRS398.exe (the folder is the portable build; the installer wraps it)
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("uvicorn") + collect_submodules("app") + collect_submodules("core") + ["restore", "verify_backup", "selftest", "argon2", "multipart", "pystray._win32"]
datas = [("app/templates", "app/templates"), ("app/static", "app/static"), ("app/i18n", "app/i18n"),
         ("app/migrations", "app/migrations"), ("core/data", "core/data"), ("VERSION", "."), ("docs/USER_GUIDE.md", "docs"), ("docs/USER_GUIDE.en.md", "docs")]
a = Analysis(["tray.py"], pathex=[".", "tools"], hiddenimports=hidden, datas=datas,
             excludes=["tkinter", "matplotlib", "pytest", "psycopg", "weasyprint", "scipy", "numpy",
                       "watchfiles", "yaml", "dotenv", "websockets", "httptools", "uvloop"])        # the extras of uvicorn[standard]: not used by the program
# Pillow only draws the tray icon: the codecs for AVIF/WebP, colour management and Tk are not needed
UNUSED_PIL = ("_avif", "_webp", "_imagingcms", "_imagingtk")
a.binaries = [b for b in a.binaries if not any(b[0].replace(chr(92), "/").startswith(f"PIL/{n}.") for n in UNUSED_PIL)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TRS398", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="TRS398")
