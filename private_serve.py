"""Run the daily AI privately over HTTPS with Tailscale Serve.

This uses Serve, never Funnel. The server stays bound to loopback.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def find_tailscale() -> str | None:
    found = shutil.which('tailscale')
    if found:
        return found
    if os.name == 'nt':
        for folder in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
            if folder:
                candidate = Path(folder) / 'Tailscale' / 'tailscale.exe'
                if candidate.is_file():
                    return str(candidate)
    return None


def hostname_from_status(status: dict) -> str:
    if status.get('BackendState') != 'Running':
        raise RuntimeError('Tailscale にログインして接続してください。')
    hostname = str(status.get('Self', {}).get('DNSName', '')).lower().rstrip('.')
    if not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net', hostname):
        raise RuntimeError('Tailscale の端末名を確認できません。MagicDNS を有効にしてください。')
    return hostname


def login_from_status(status: dict) -> str:
    self_status = status.get('Self')
    users = status.get('User')
    profile = users.get(str(self_status.get('UserID'))) if isinstance(self_status, dict) and isinstance(users, dict) else None
    raw_login = profile.get('LoginName') if isinstance(profile, dict) else None
    login = raw_login.strip().casefold() if isinstance(raw_login, str) else ''
    if not login or any(char in login for char in '\r\n\x00'):
        raise RuntimeError('Tailscale の本人ログイン名を確認できません。ユーザー所有の端末でログインしてください。')
    return login


def main() -> int:
    tailscale = find_tailscale()
    if not tailscale:
        print('Tailscale が見つかりません。公式アプリをインストールしてログインしてください。', file=sys.stderr)
        return 1
    status = subprocess.run([tailscale, 'status', '--json'], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=15)
    if status.returncode:
        print(f'Tailscale の状態を読めません: {status.stderr.strip()}', file=sys.stderr)
        return 1
    connection = json.loads(status.stdout)
    hostname = hostname_from_status(connection)
    login = login_from_status(connection)

    from persona_chat_prototype import load_config
    if load_config().get('mode') != 'daily':
        raise RuntimeError('日常モードでのみ使用できます。')
    try:
        with socket.create_connection(('127.0.0.1', 8765), timeout=0.3):
            raise RuntimeError('ローカルサーバーが起動中です。先に停止してから実行してください。')
    except ConnectionRefusedError:
        pass

    os.environ['EXHIBITION_ACCESS_TOKEN'] = ''
    os.environ['EXHIBITION_HTTPS_PROXY_HOST'] = hostname
    os.environ['EXHIBITION_TAILSCALE_LOGIN'] = login

    from exhibition_server import make_server
    server = make_server()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    print(f'本人の tailnet 内だけで利用: https://{hostname}/', flush=True)
    print('Mac・スマホも同じ Tailscale アカウントで接続してください。', flush=True)
    print('初回は Tailscale 側で HTTPS の許可画面が出る場合があります。', flush=True)
    print('終了するときは Ctrl+C。公開インターネット向けの Funnel は使用しません。', flush=True)
    try:
        return subprocess.run([tailscale, 'serve', '8765'], cwd=ROOT).returncode
    except KeyboardInterrupt:
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f'起動できませんでした: {exc}') from exc
