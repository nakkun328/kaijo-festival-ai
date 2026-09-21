from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import psutil


ROOT = Path(__file__).resolve().parents[1]
STATUS_FILE = ROOT / "data" / ".public-tunnel-status.json"
HOST = "127.0.0.1"
PORT = 8765


def _token_from_url(value: str, expected_segment: str) -> str:
    parts = [part for part in urlparse(value).path.split("/") if part]
    if len(parts) != 2 or parts[0] != expected_segment or not parts[1]:
        raise RuntimeError(f"{expected_segment} URLの形式が不正です。")
    return parts[1]


def _wait_for_port(timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def main() -> int:
    if not STATUS_FILE.is_file():
        raise RuntimeError("公開トンネルの状態ファイルがありません。先に public_tunnel.py を起動してください。")
    status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    old_pid = int(status["server_pid"])
    visitor_token = _token_from_url(str(status["invite_url"]), "invite")
    admin_token = _token_from_url(str(status["admin_url"]), "admin")

    old_process = psutil.Process(old_pid)
    command_line = " ".join(old_process.cmdline()).casefold()
    if "public_tunnel.py" not in command_line and "exhibition_server.py" not in command_line:
        raise RuntimeError(f"PID {old_pid} は文化祭案内AIの公開サーバーではありません。停止しません。")

    old_process.terminate()
    try:
        old_process.wait(timeout=8)
    except psutil.TimeoutExpired:
        old_process.kill()
        old_process.wait(timeout=5)

    environment = os.environ.copy()
    environment["EXHIBITION_ACCESS_TOKEN"] = visitor_token
    environment["EXHIBITION_ADMIN_TOKEN"] = admin_token
    output_log = (ROOT / "tmp" / "public-backend-current.out.log").open("w", encoding="utf-8")
    error_log = (ROOT / "tmp" / "public-backend-current.err.log").open("w", encoding="utf-8")
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    backend = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "exhibition_server.py")],
        cwd=ROOT,
        env=environment,
        stdout=output_log,
        stderr=error_log,
        creationflags=creation_flags,
    )
    output_log.close()
    error_log.close()
    if not _wait_for_port():
        backend.terminate()
        raise RuntimeError("更新後のサーバーが90秒以内に起動しませんでした。ログを確認してください。")

    status["server_pid"] = backend.pid
    status["backend_restarted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    temporary = STATUS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATUS_FILE)
    print(f"backend pid={backend.pid}")
    print(status["invite_url"])
    print(status["admin_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
