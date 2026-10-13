"""Start the program: the web server on this computer (http://localhost:8000). Data are in the folder `data`.

    python run.py [--lan] [--port 8000]

--lan lets other computers of the network open the program (http://<name of this computer>:8000).
"""
import argparse
import threading
import webbrowser

import uvicorn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lan", action="store_true")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{a.port}")).start()
    uvicorn.run("app.main:app", host="0.0.0.0" if a.lan else "127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
