from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from exhibition_server import make_server


ROOT = Path(__file__).resolve().parent
KIOSK_URL = "http://127.0.0.1:8765/"
STOP_FILE = ROOT / "data" / ".stop-kiosk"
PROFILE_DIR = ROOT / "data" / "kiosk-browser-profile"


def find_browser(preferred: str = "") -> Path:
    candidates: list[Path] = []
    if preferred:
        candidates.append(Path(preferred))
    for environment, relative in (
        ("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
        ("PROGRAMFILES", "Microsoft/Edge/Application/msedge.exe"),
        ("LOCALAPPDATA", "Microsoft/Edge/Application/msedge.exe"),
        ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
        ("PROGRAMFILES(X86)", "Google/Chrome/Application/chrome.exe"),
        ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
    ):
        base = os.environ.get(environment)
        if base:
            candidates.append(Path(base) / relative)
    for command in ("msedge", "chrome"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    browser = next((path for path in candidates if path.is_file()), None)
    if browser is None:
        raise FileNotFoundError("Microsoft EdgeまたはGoogle Chromeが見つかりません。")
    return browser


def browser_command(browser: Path, url: str) -> list[str]:
    common = [
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--disable-session-crashed-bubble",
        "--disable-features=Translate,msEdgeSidebarV2",
        "--autoplay-policy=no-user-gesture-required",
    ]
    if browser.name.casefold() == "msedge.exe":
        return [str(browser), "--kiosk", url, "--edge-kiosk-type=fullscreen", *common]
    return [str(browser), "--kiosk", url, *common]


def wait_until_ready(url: str, timeout_seconds: float = 45.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.4)
    raise TimeoutError("展示サーバーの起動確認がタイムアウトしました。")


def run(url: str, browser_path: str = "", restart_browser: bool = True) -> int:
    STOP_FILE.unlink(missing_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    browser = find_browser(browser_path)
    server = make_server()
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    wait_until_ready(url)
    print(f"キオスク表示: {url}")
    print(f"ブラウザー: {browser}")
    try:
        while not STOP_FILE.exists():
            process = subprocess.Popen(browser_command(browser, url), cwd=ROOT)
            while process.poll() is None and not STOP_FILE.exists():
                time.sleep(1)
            if STOP_FILE.exists():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                break
            if not restart_browser:
                break
            time.sleep(2)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        STOP_FILE.unlink(missing_ok=True)
        server.shutdown()
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="文化祭案内AIを本番キオスクモードで起動します。")
    parser.add_argument("--url", default=KIOSK_URL)
    parser.add_argument("--browser", default=os.getenv("KIOSK_BROWSER", ""))
    parser.add_argument("--no-restart", action="store_true", help="ブラウザー終了時に再起動しません。")
    args = parser.parse_args()
    return run(args.url, args.browser, not args.no_restart)


if __name__ == "__main__":
    raise SystemExit(main())
