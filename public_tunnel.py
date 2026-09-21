from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STATUS_FILE = ROOT / "data" / ".public-tunnel-status.json"


def find_cloudflared() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    candidates = (
        ROOT / "tools" / "cloudflared.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "cloudflared" / "cloudflared.exe",
        Path(os.environ.get("ProgramFiles", "")) / "cloudflared" / "cloudflared.exe",
    )
    return next((str(path) for path in candidates if path.is_file()), None)


def main() -> int:
    STATUS_FILE.unlink(missing_ok=True)
    cloudflared = find_cloudflared()
    if not cloudflared:
        print("cloudflared が見つかりません。先にインストールしてください。", file=sys.stderr)
        return 1

    token = secrets.token_urlsafe(32)
    admin_token = secrets.token_urlsafe(32)
    os.environ["EXHIBITION_ACCESS_TOKEN"] = token
    os.environ["EXHIBITION_ADMIN_TOKEN"] = admin_token

    try:
        from scripts.import_kaijofes_website import update_knowledge

        record_count = update_knowledge(ROOT / "data" / "festival" / "website_knowledge.json")
        print(f"海城祭公式サイトの案内情報を更新しました（{record_count}件）。", flush=True)
    except Exception as exc:
        print(
            f"公式サイト情報を更新できなかったため、保存済みデータを使います: {exc}",
            file=sys.stderr,
            flush=True,
        )

    from exhibition_server import make_server

    server = make_server()
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    tunnel = subprocess.Popen(
        [cloudflared, "tunnel", "--url", "http://127.0.0.1:8765", "--no-autoupdate"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    invite_shown = False
    try:
        assert tunnel.stdout is not None
        for line in tunnel.stdout:
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if match and not invite_shown:
                invite_url = f"{match.group(0)}/invite/{token}"
                admin_url = f"{match.group(0)}/admin/{admin_token}"
                print("\n=== 招待リンク（このリンクを知る人だけが入れます） ===")
                print(invite_url)
                print("\n=== 管理画面（運営者だけに共有） ===")
                print(admin_url)
                print("=== 終了するときは Ctrl+C ===\n")
                STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
                STATUS_FILE.write_text(
                    json.dumps({"invite_url": invite_url, "admin_url": admin_url, "server_pid": os.getpid()}),
                    encoding="utf-8",
                )
                invite_shown = True
            elif "ERR" in line or "error" in line.casefold():
                print(line.rstrip())
        return tunnel.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        STATUS_FILE.unlink(missing_ok=True)
        tunnel.terminate()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
