import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from daily_store import DailyStore


class DailyStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'daily.db'
        self.store = DailyStore(self.path)
        self.a = self.store.create_identity()
        self.b = self.store.create_identity()

    def test_persistence_and_separation(self):
        self.store.append_turn(self.a, '昨日は作曲した', '何を作ったの？')
        memory = self.store.save_memory(self.a, '作曲に取り組んでいる')
        reopened = DailyStore(self.path)
        self.assertEqual(len(reopened.history(self.a)), 2)
        self.assertEqual(reopened.history(self.b), [])
        self.assertEqual(reopened.memories(self.b), [])
        self.assertEqual(reopened.memories(self.a)[0]['id'], memory)
        with self.assertRaises(ValueError):
            reopened.save_memory(self.b, '書き換え', memory)
        with self.assertRaises(ValueError):
            reopened.delete_memory(self.b, memory)
        self.assertEqual(reopened.memories(self.a)[0]['content'], '作曲に取り組んでいる')

    def test_edit_delete_and_history_reset(self):
        memory = self.store.save_memory(self.a, 'ピアノが好き')
        self.store.save_memory(self.a, 'ギターが好き', memory)
        self.assertEqual(self.store.memories(self.a)[0]['content'], 'ギターが好き')
        self.store.append_turn(self.a, 'こんにちは', 'こんにちは')
        self.store.clear_history(self.a)
        self.assertEqual(self.store.history(self.a), [])
        self.assertEqual(len(self.store.memories(self.a)), 1)
        self.store.delete_memory(self.a, memory)
        self.assertEqual(DailyStore(self.path).memories(self.a), [])

    def test_unknown_identity_and_empty_memory_rejected(self):
        with self.assertRaises(ValueError):
            self.store.history('x' * 43)
        with self.assertRaises(ValueError):
            self.store.save_memory(self.a, '  ')

    def test_sources_survive_reopening_without_polluting_model_history(self):
        evidence = {'sources':[{'title':'天気', 'url':'https://open-meteo.com/'}], 'retrievedAt':'2026-09-22T00:00:00Z'}
        self.store.append_turn(self.a, '天気は？', '予報です[1]', evidence)
        reopened = DailyStore(self.path)
        self.assertEqual(reopened.history(self.a, include_sources=True)[-1]['sources'], evidence['sources'])
        self.assertNotIn('sources', reopened.history(self.a)[-1])
        self.assertEqual(reopened.history(self.b, include_sources=True), [])

    def test_concurrent_turns_are_atomic(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n: self.store.append_turn(self.a, str(n), str(n)), range(10)))
        messages = self.store.history(self.a)
        self.assertEqual(len(messages), 20)
        for i in range(0, 20, 2):
            self.assertEqual(messages[i]['role'], 'user')
            self.assertEqual(messages[i + 1]['role'], 'assistant')
            self.assertEqual(messages[i]['content'], messages[i + 1]['content'])

    def test_themes_persist_and_are_owner_scoped(self):
        first = self.store.save_theme(self.a, {
            'title':'進路', 'goal':'方向を決める', 'options':'大学か就職',
            'open_questions':'費用', 'decisions':'今週調べる'})
        reopened = DailyStore(self.path)
        self.assertEqual(reopened.themes(self.a)['activeThemeId'], first)
        self.assertEqual(reopened.active_theme(self.a)['goal'], '方向を決める')
        self.assertEqual(reopened.themes(self.b)['themes'], [])
        with self.assertRaises(ValueError):
            reopened.save_theme(self.b, {'title':'横取り'}, first)
        with self.assertRaises(ValueError):
            reopened.select_theme(self.b, first)
        with self.assertRaises(ValueError):
            reopened.delete_theme(self.b, first)
        reopened.save_theme(self.a, {'title':'進路', 'decisions':'大学見学を予約'}, first)
        self.assertEqual(reopened.active_theme(self.a)['decisions'], '大学見学を予約')
        reopened.select_theme(self.a, None)
        self.assertIsNone(reopened.active_theme(self.a))
        reopened.select_theme(self.a, first)
        reopened.delete_theme(self.a, first)
        self.assertIsNone(DailyStore(self.path).themes(self.a)['activeThemeId'])

    def test_theme_history_ignores_unrelated_conversation(self):
        theme = self.store.save_theme(self.a, {'title':'進路'})
        self.store.append_turn(self.a, '大学か就職か', '費用と学び方で比較しよう')
        self.store.select_theme(self.a, None)
        self.store.append_turn(self.a, '今日の夕飯', 'カレーはどう？')
        self.assertEqual([item['content'] for item in DailyStore(self.path).theme_history(self.a, theme)],
                         ['大学か就職か', '費用と学び方で比較しよう'])
        with self.assertRaises(ValueError):
            self.store.theme_history(self.b, theme)

    def test_account_registration_session_and_anonymous_migration(self):
        self.store.append_turn(self.a, '相談', '返答')
        self.store.save_memory(self.a, 'ギターが好き')
        theme = self.store.save_theme(self.a, {'title':'進路', 'goal':'決める'})
        with self.assertRaises(ValueError):
            self.store.register_account(self.a, 'test_user', 'long-password-123')
        owner, recovery_code = self.store.register_account(self.a, 'test_user', 'long-password-123', migrate_local=True)
        self.assertEqual(self.store.memories(self.a), [])
        self.assertEqual(self.store.history(self.a), [])
        self.assertEqual(self.store.memories(owner)[0]['content'], 'ギターが好き')
        self.assertEqual(self.store.themes(owner)['activeThemeId'], theme)
        self.assertEqual(len(self.store.history(owner)), 2)
        self.assertEqual(self.store.authenticate_account('TEST_USER', 'long-password-123'), owner)
        with self.assertRaises(ValueError):
            self.store.authenticate_account('test_user', 'wrong-password')
        session = self.store.new_session(owner)
        self.assertEqual(DailyStore(self.path).session_owner(session), owner)
        recovered_owner, new_code = self.store.recover_account('test_user', recovery_code, 'changed-password-123')
        self.assertEqual(recovered_owner, owner)
        self.assertNotEqual(new_code, recovery_code)
        self.assertIsNone(self.store.session_owner(session))
        with self.assertRaises(ValueError):
            self.store.recover_account('test_user', recovery_code, 'another-password-123')
        with self.assertRaises(ValueError):
            self.store.authenticate_account('test_user', 'long-password-123')
        self.assertEqual(self.store.authenticate_account('test_user', 'changed-password-123'), owner)
        with self.assertRaises(ValueError):
            self.store.reissue_recovery_code(owner, 'wrong-password')
        reissued = self.store.reissue_recovery_code(owner, 'changed-password-123')
        self.assertNotEqual(reissued, new_code)
        with self.assertRaises(ValueError):
            self.store.recover_account('test_user', new_code, 'third-password-123')
        self.store.end_session(session)
        self.assertIsNone(self.store.session_owner(session))

    def test_account_merge_preserves_both_sides_and_rejects_overflow(self):
        owner, _ = self.store.register_account(self.a, 'account2', 'another-long-password')
        self.store.save_memory(owner, 'アカウント側')
        self.store.save_memory(self.b, 'ブラウザ側')
        counts = self.store.migrate_local(self.b, owner)
        self.assertEqual(counts['memories'], 1)
        self.assertEqual(self.store.memories(self.b), [])
        self.assertEqual({item['content'] for item in self.store.memories(owner)},
                         {'アカウント側', 'ブラウザ側'})
