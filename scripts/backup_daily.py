"""Back up or restore the daily AI SQLite database.

Backups contain private conversations and password hashes. Keep them private.
"""
from __future__ import annotations

import argparse
import os
import socket
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / 'data' / 'daily.db'
BACKUP_DIR = ROOT / 'data' / 'backups'
REQUIRED_TABLES = {'identities', 'daily_messages', 'daily_memories',
                   'daily_themes', 'daily_accounts'}


def validate_database(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f'データベースが見つかりません: {path}')
    with closing(sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('データベースの整合性チェックに失敗しました。')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES <= tables:
            raise ValueError('日常AIのデータベースではありません。')


def snapshot(source: Path, destination: Path) -> Path:
    validate_database(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f'上書きしません: {destination}')
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
    try:
        validate_database(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def server_running() -> bool:
    try:
        with socket.create_connection(('127.0.0.1', 8765), timeout=0.3):
            return True
    except OSError:
        return False


def restore(backup: Path, database: Path, *, confirmed: bool = False) -> Path | None:
    if not confirmed:
        raise ValueError('復元には --confirm-restore が必要です。')
    if server_running():
        raise RuntimeError('先に日常AIサーバーを停止してください（127.0.0.1:8765 が使用中）。')
    validate_database(backup)
    if backup.resolve() == database.resolve():
        raise ValueError('復元元と復元先が同じです。')
    if any(Path(str(database) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise RuntimeError('SQLiteの作業ファイルが残っています。サーバー停止を確認してください。')
    database.parent.mkdir(parents=True, exist_ok=True)
    previous = None
    if database.exists():
        previous = BACKUP_DIR / f'daily-pre-restore-{datetime.now():%Y%m%d-%H%M%S-%f}.db'
        snapshot(database, previous)
    fd, temporary = tempfile.mkstemp(prefix='.daily-restore-', suffix='.db', dir=database.parent)
    os.close(fd)
    temp_path = Path(temporary)
    try:
        with closing(sqlite3.connect(backup)) as src, closing(sqlite3.connect(temp_path)) as dst:
            src.backup(dst)
        validate_database(temp_path)
        os.replace(temp_path, database)
    finally:
        temp_path.unlink(missing_ok=True)
    return previous


def main() -> int:
    parser = argparse.ArgumentParser(description='日常AIデータのバックアップ・復元')
    parser.add_argument('--database', type=Path, default=DATABASE, help=argparse.SUPPRESS)
    parser.add_argument('--restore', type=Path, metavar='BACKUP')
    parser.add_argument('--confirm-restore', action='store_true')
    args = parser.parse_args()
    if args.restore:
        previous = restore(args.restore, args.database, confirmed=args.confirm_restore)
        print(f'復元しました: {args.database}')
        if previous:
            print(f'復元前のデータ: {previous}')
    else:
        if args.confirm_restore:
            parser.error('--confirm-restore は --restore と一緒に指定してください。')
        destination = BACKUP_DIR / f'daily-{datetime.now():%Y%m%d-%H%M%S-%f}.db'
        print(f'バックアップしました: {snapshot(args.database, destination)}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        raise SystemExit(f'失敗: {exc}') from exc
