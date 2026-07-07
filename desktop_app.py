"""
Desktop launcher for the standalone .exe build.
Runs the Streamlit server in-process (no subprocess — a frozen PyInstaller
exe has no separate python.exe to shell out to) and opens it in the user's
default browser, same as running `streamlit run app.py` normally.

Deliberately does NOT import any app modules (core.*, streamlit_folium,
folium, etc.) at this top level. Custom Streamlit components like
streamlit_folium call components.v1.declare_component() at their own import
time, which only registers the component if a Streamlit ScriptRunContext is
already active — importing them here, before stcli.main() has started the
Streamlit runtime, would silently register nothing, and since Python caches
the import, app.py's later (correct) import would just reuse the already-broken
module. PyInstaller still needs to know about these modules to bundle them,
which is handled via hiddenimports in geo_extractor.spec instead.
"""

import os
import socket
import sys
import threading
import time
import webbrowser

PORT = 8765


def _resource_path(relative_path: str) -> str:
    """Resolve a path next to this script, both in dev and when frozen
    (PyInstaller onefile extracts bundled data files under sys._MEIPASS)."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def _open_browser_when_ready(port: int, timeout: float = 30.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.3)
    webbrowser.open(f"http://127.0.0.1:{port}")


def _pick_folder_and_exit() -> None:
    """Special mode: show a native folder-picker dialog and print the chosen
    path, then exit — nothing else. Invoked by app.py's folder-browse button
    re-launching this same exe with --pick-folder, since a frozen exe has no
    separate python.exe to subprocess a one-off tkinter script into (which is
    what the non-frozen version does, and for the same reason: tkinter needs
    a real main thread, which Streamlit's own script-execution thread isn't)."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    path = filedialog.askdirectory(title="フォルダを選択してください")
    root.destroy()
    print(path)


def main() -> None:
    threading.Thread(target=_open_browser_when_ready, args=(PORT,), daemon=True).start()

    print("起動中です。しばらくするとブラウザが自動で開きます。")
    print("終了するには、このウィンドウを閉じてください。")

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        _resource_path("app.py"),
        "--server.port", str(PORT),
        "--server.headless", "true",
        "--server.address", "127.0.0.1",
        "--global.developmentMode", "false",
        "--browser.gatherUsageStats", "false",
    ]
    stcli.main()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--pick-folder":
        _pick_folder_and_exit()
    else:
        main()
