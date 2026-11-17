"""MineHub desktop entry: hidden Stash, same-origin gateway, Chinese tray menu."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from .config import DATA, TOOLS, ensure_dirs
from .stash import CONFIG, STASH_DIR, STASH_EXE, ensure_config

VENV_PY = Path(__file__).resolve().parent.parent / ".venv" / "Scripts" / "python.exe"

PUBLIC_PORT = 9999
INTERNAL_PORT = 9998
LOG_DIR = DATA / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

MENU = [
    ("视频", "/scenes"),
    ("图片", "/images"),
    ("集合", "/groups"),
    ("标记", "/scenes/markers"),
    ("图库", "/galleries"),
    ("演员", "/performers"),
    ("工作室", "/studios"),
    ("标签", "/tags"),
]


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _hidden_startup() -> subprocess.STARTUPINFO:
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return si


def start_stash() -> subprocess.Popen | None:
    if port_open(INTERNAL_PORT):
        return None
    ensure_config()
    log = open(LOG_DIR / "stash_stdout.log", "a", encoding="utf-8", errors="replace")
    # A new hidden console makes Stash see a terminal and skip its own tray icon.
    p = subprocess.Popen(
        [str(STASH_EXE), "--config", str(CONFIG), "--port", str(INTERNAL_PORT), "--host", "127.0.0.1"],
        stdout=log, stderr=subprocess.STDOUT, cwd=str(STASH_DIR),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        startupinfo=_hidden_startup(),
    )
    return p


def start_gateway() -> subprocess.Popen | None:
    if port_open(PUBLIC_PORT):
        return None
    log = open(LOG_DIR / "gateway.log", "a", encoding="utf-8", errors="replace")
    p = subprocess.Popen(
        [str(VENV_PY if VENV_PY.is_file() else sys.executable), "-m", "mh.gateway", str(PUBLIC_PORT), str(INTERNAL_PORT)],
        stdout=log, stderr=subprocess.STDOUT, cwd=str(Path(__file__).resolve().parent.parent),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return p


def wait_ports(timeout: float = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(PUBLIC_PORT) and port_open(INTERNAL_PORT):
            return True
        time.sleep(0.5)
    return False


def suppress_stash_tray(pid: int | None, timeout: float = 15) -> bool:
    if not pid:
        return False
    import win32con
    import win32gui
    import win32process

    deadline = time.time() + timeout
    while time.time() < deadline:
        handles: list[int] = []

        def collect(hwnd, _):
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if window_pid == pid and win32gui.GetClassName(hwnd) == "SystrayClass":
                handles.append(hwnd)

        win32gui.EnumWindows(collect, None)
        if handles:
            for hwnd in handles:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            until = time.time() + 3
            while time.time() < until and any(win32gui.IsWindow(h) for h in handles):
                time.sleep(0.1)
            return not any(win32gui.IsWindow(h) for h in handles)
        time.sleep(0.3)
    return False


def icon_image() -> Image.Image:
    path = TOOLS / "stash" / "icon.png"
    if path.is_file():
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            pass
    img = Image.new("RGBA", (64, 64), (31, 111, 235, 255))
    d = ImageDraw.Draw(img)
    d.text((18, 18), "M", fill=(255, 255, 255, 255))
    return img


def main() -> None:
    import win32api
    import win32event

    log = open(LOG_DIR / "desktop.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    print(time.strftime("[%Y-%m-%d %H:%M:%S] MineHub desktop starting"), flush=True)

    mutex = win32event.CreateMutex(None, False, "MineHubDesktopTray")
    if win32api.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return
    ensure_dirs()
    ensure_config()
    stash = start_stash()
    gateway = start_gateway()
    if not wait_ports():
        print("MineHub 服务启动超时，请查看 data/logs/gateway.log / stash_stdout.log", flush=True)
        return
    if stash is not None:
        print("Stash tray suppressed:", suppress_stash_tray(stash.pid), flush=True)

    def open_path(path: str):
        webbrowser.open(f"http://127.0.0.1:{PUBLIC_PORT}{path}")

    def open_action(path: str):
        def action(_icon, _item):
            open_path(path)

        return action

    def quit_app(icon, _item):
        icon.stop()
        for p in (gateway, stash):
            if p is None:
                continue
            subprocess.run(
                ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                capture_output=True,
            )

    items = [
        pystray.MenuItem("搜索", lambda i, _: open_path("/mh")),
        pystray.MenuItem("打开 MineHub", lambda i, _: open_path("")),
    ]
    items.append(pystray.Menu.SEPARATOR)
    items += [pystray.MenuItem(label, open_action(path)) for label, path in MENU]
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("退出 MineHub", quit_app))
    icon = pystray.Icon("MineHub", icon_image(), "MineHub", pystray.Menu(*items))
    icon.run()


if __name__ == "__main__":
    main()