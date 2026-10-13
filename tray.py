"""The program as a Windows tray application: the server runs in the background, the icon near the clock opens it.

    pythonw tray.py          (or trs398.exe after the build)

Menu: open, backup now, open the data folder, start with Windows, let other computers connect, quit.
Settings (port, network access) are kept in <data>/settings.json. Only one copy runs at a time.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

APP_NAME = "TRS398"

# a program without a console window (the released build) has no stdin/stdout/stderr: give the libraries something to write to
for _name, _mode in (("stdin", "r"), ("stdout", "w"), ("stderr", "w")):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, _mode, encoding="utf-8"))


def base_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def choose_data_dir() -> Path:
    """TRS_DATA; a portable copy (file portable.flag next to the program) keeps `data` beside it; else %LOCALAPPDATA%/TRS398/data."""
    if os.environ.get("TRS_DATA"):
        return Path(os.environ["TRS_DATA"])
    if (base_dir() / "portable.flag").exists() or not getattr(sys, "frozen", False):
        return base_dir() / "data"
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME / "data"


if getattr(sys, "frozen", False):                          # the released build shows its version without "+dev"
    try:
        os.environ.setdefault("TRS_VERSION", (Path(sys._MEIPASS) / "VERSION").read_text(encoding="utf-8").strip())
    except OSError:
        pass
os.environ["TRS_DATA"] = str(choose_data_dir())
Path(os.environ["TRS_DATA"]).mkdir(parents=True, exist_ok=True)

SETTINGS = Path(os.environ["TRS_DATA"]) / "settings.json"


def load_settings() -> dict:
    try:
        return {"port": 8000, "lan": False, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return {"port": 8000, "lan": False}


def save_settings(s: dict) -> None:
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


# ---- start with Windows (the Run key of the current user: no administrator rights needed)
def autostart_command() -> str:
    exe = sys.executable if getattr(sys, "frozen", False) else f'"{Path(sys.executable).with_name("pythonw.exe")}" "{Path(__file__).resolve()}"'
    return f'"{exe}"' if getattr(sys, "frozen", False) else exe


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except (OSError, ImportError):
        return False


def set_autostart(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Server:
    def __init__(self, port: int, lan: bool):
        import uvicorn
        from app.main import app
        self.server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0" if lan else "127.0.0.1", port=port, log_level="warning", log_config=None))
        self.thread = threading.Thread(target=self.server.run, name="trs398-server", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)


def make_icon():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(31, 78, 140, 255))
    d.ellipse((14, 14, 50, 50), outline=(255, 255, 255, 255), width=4)
    d.ellipse((27, 27, 37, 37), fill=(255, 255, 255, 255))
    return img


def lan_address(port: int) -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return f"http://{s.getsockname()[0]}:{port}"
    except OSError:
        return f"http://{socket.gethostname()}:{port}"


def run_console_tool(name: str) -> int:
    """`TRS398.exe restore|verify`: the tools of the folder tools/ in a console window of their own."""
    import ctypes
    if ctypes.windll.kernel32.AllocConsole():
        sys.stdin = open("CONIN$", "r", encoding="utf-8")
        sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8")
    code = 0
    try:
        import importlib
        sys.path.insert(0, str(base_dir() / "tools"))
        sys.argv = [name] + sys.argv[2:]
        importlib.import_module({"restore": "restore", "verify": "verify_backup"}[name]).main()
    except SystemExit as e:
        code = 0 if e.code in (None, 0) else 1
        if e.code not in (None, 0):
            print(e.code)
    except Exception as e:                                  # noqa: BLE001
        code = 1
        print(f"Error: {e}")
    try:
        input("\nEnter - закрыть / close ")
    except EOFError:
        pass
    return code


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("restore", "verify"):
        return run_console_tool(sys.argv[1])
    import pystray
    settings = load_settings()
    port = int(settings["port"])
    if port_busy(port):                                     # a copy is already running: just open it
        webbrowser.open(f"http://localhost:{port}")
        return 0
    state = {"server": Server(port, settings["lan"])}
    state["server"].start()
    url = f"http://localhost:{port}"

    def open_app(icon=None, item=None):
        webbrowser.open(url)

    def backup_now(icon, item):
        from app import backups
        ok = backups.request_now()
        icon.notify("Резервная копия сделана." if ok else "Не удалось сделать копию: папка недоступна для записи.", "TRS-398")

    def open_data(icon, item):
        os.startfile(os.environ["TRS_DATA"])  # noqa: S606

    def restore(icon, item):
        state["server"].stop()
        cmd = [sys.executable, "restore"] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve()), "restore"]
        subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        icon.stop()

    def toggle_autostart(icon, item):
        set_autostart(not autostart_enabled())

    def toggle_lan(icon, item):
        settings["lan"] = not settings["lan"]
        save_settings(settings)
        state["server"].stop()
        state["server"] = Server(port, settings["lan"])
        state["server"].start()
        if settings["lan"]:
            icon.notify(f"Другие компьютеры сети: {lan_address(port)}\nПри первом включении Windows спросит разрешение брандмауэра.", "TRS-398")

    def quit_app(icon, item):
        state["server"].stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Открыть программу", open_app, default=True),
        pystray.MenuItem("Сделать резервную копию", backup_now),
        pystray.MenuItem("Папка с данными", open_data),
        pystray.MenuItem("Восстановить из копии…", restore),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Запускать вместе с Windows", toggle_autostart, checked=lambda item: autostart_enabled()),
        pystray.MenuItem("Разрешить подключение с других компьютеров", toggle_lan, checked=lambda item: settings["lan"]),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app),
    )
    icon = pystray.Icon(APP_NAME, make_icon(), "TRS-398", menu)
    threading.Timer(1.5, open_app).start()
    icon.run()
    return 0


def report_crash() -> None:
    """A failure at the start: the text goes to crash.log in the data folder and into a message box (no console to show it)."""
    import traceback
    text = traceback.format_exc()
    try:
        (Path(os.environ["TRS_DATA"]) / "crash.log").write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, f"TRS-398 не запустилась / failed to start."+chr(10)*2+f"{text[-900:]}"+chr(10)*2+f"File: {Path(os.environ['TRS_DATA']) / 'crash.log'}", "TRS-398", 0x10)
    except Exception:                                       # noqa: BLE001
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:                                       # noqa: BLE001
        report_crash()
        sys.exit(1)

