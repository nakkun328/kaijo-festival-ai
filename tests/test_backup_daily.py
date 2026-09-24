import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from daily_store import DailyStore
from scripts.backup_daily import restore, snapshot, validate_database


class DailyBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'daily.db'
        self.store = DailyStore(self.db_path)
        self.owner = self.store.create_identity()
        self.store.save_memory(self.owner, '作曲が好き')
        self.store.save_theme(self.owner, {'title': '進路', 'goal': '決める'})
        self.store.append_turn(self.owner, 'こんにちは', 'こんにちは')

    def test_snapshot_and_restore_roundtrip_preserves_data(self):
        backup = snapshot(self.db_path, self.root / 'backup.db')
        self.store.save_memory(self.owner, '後から追加')
        with patch('scripts.backup_daily.server_running', return_value=False), \
             patch('scripts.backup_daily.BACKUP_DIR', self.root / 'backups'):
            previous = restore(backup, self.db_path, confirmed=True)
        self.assertIsNotNone(previous)
        self.assertTrue(previous.exists())
        self.assertEqual(len(DailyStore(previous).memories(self.owner)), 2)
        reopened = DailyStore(self.db_path)
        self.assertEqual([m['content'] for m in reopened.memories(self.owner)], ['作曲が好き'])
        self.assertEqual(reopened.themes(self.owner)['themes'][0]['title'], '進路')
        self.assertEqual(len(reopened.history(self.owner)), 2)

    def test_restore_requires_confirmation_and_stopped_server(self):
        backup = snapshot(self.db_path, self.root / 'backup.db')
        with self.assertRaisesRegex(ValueError, 'confirm-restore'):
            restore(backup, self.db_path)
        with patch('scripts.backup_daily.server_running', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'サーバーを停止'):
                restore(backup, self.db_path, confirmed=True)

    def test_invalid_or_existing_backup_is_rejected(self):
        invalid = self.root / 'invalid.db'
        with closing(sqlite3.connect(invalid)) as db:
            db.execute('CREATE TABLE unrelated (id INTEGER)')
        with self.assertRaisesRegex(ValueError, '日常AI'):
            validate_database(invalid)
        existing = self.root / 'existing.db'
        existing.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            snapshot(self.db_path, existing)
        self.assertEqual(existing.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
