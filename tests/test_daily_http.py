import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError
from http.cookiejar import CookieJar
from daily_store import DailyStore
from exhibition_server import ExhibitionApp, ExhibitionHTTPServer, Handler
from test_exhibition_server import CONFIG
from model_providers import ProviderStatus


class DailyHttpTests(unittest.TestCase):
    def test_new_theme_draft_focuses_latest_consultation(self):
        with tempfile.TemporaryDirectory() as directory:
            app = ExhibitionApp(copy.deepcopy(CONFIG))
            app.config['mode'] = 'daily'
            app.daily_store = DailyStore(Path(directory) / 'daily.db')
            app.owner = app.daily_store.create_identity()
            app.daily_store.append_turn(app.owner, '週末は映画を見る。', '楽しんで。')
            latest = '進路は大学か就職かで迷う。費用が未確認。'
            app.daily_store.append_turn(app.owner, latest, '費用を確認しよう。')
            app.history = app.daily_store.history(app.owner)
            fake = MagicMock()
            fake.status.return_value = ProviderStatus('openai', 'Test', 'test', True)
            fake.generate.return_value = '{"title":"進路","goal":"決める","options":"大学・就職","open_questions":"費用","decisions":""}'
            app.providers['openai'] = fake
            self.assertEqual(app.draft_theme()['title'], '進路')
            payload = json.loads(fake.generate.call_args.args[1][0]['content'])
            self.assertEqual(payload['focus'], latest)
            self.assertIn('古い別話題', fake.generate.call_args.args[0])
            app.daily_store.append_turn(app.owner, 'ありがとう。', 'どういたしまして。')
            app.history = app.daily_store.history(app.owner)
            app.draft_theme()
            payload = json.loads(fake.generate.call_args.args[1][0]['content'])
            self.assertEqual(payload['focus'], latest)

    def test_account_cross_device_logout_and_confirmed_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            app = ExhibitionApp(copy.deepcopy(CONFIG))
            app.config['mode'] = 'daily'
            app.daily_store = DailyStore(Path(directory) / 'daily.db')
            app.access_token = ''
            class TestHandler(Handler):
                pass
            TestHandler.app = app
            server = ExhibitionHTTPServer(('127.0.0.1', 0), TestHandler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                a = build_opener(HTTPCookieProcessor(CookieJar()))
                b = build_opener(HTTPCookieProcessor(CookieJar()))
                c = build_opener(HTTPCookieProcessor(CookieJar()))
                def request(client, path, body=None, origin=True):
                    headers = {'Content-Type':'application/json'}
                    if body is not None and origin:
                        headers['Origin'] = base
                    data = None if body is None else json.dumps(body).encode()
                    with client.open(Request(base + path, data=data, headers=headers)) as response:
                        return json.load(response)
                request(a, '/api/memories', {'content':'共通の記憶'})
                request(b, '/api/memories', {'content':'端末Bだけの記憶'})
                counts = request(a, '/api/account')['localCounts']
                self.assertEqual(counts['memories'], 1)
                with self.assertRaises(HTTPError) as missing_confirm:
                    request(a, '/api/account/register',
                            {'username':'user_a', 'password':'safe-password-123'})
                self.assertEqual(missing_confirm.exception.code, 400)
                registered = request(a, '/api/account/register',
                                     {'username':'user_a', 'password':'safe-password-123', 'migrateLocal':True})
                self.assertEqual(len(registered['recoveryCode']), 43)
                self.assertTrue(request(a, '/api/account')['signedIn'])
                self.assertEqual(request(a, '/api/memories')['memories'][0]['content'], '共通の記憶')
                self.assertEqual(request(c, '/api/memories')['memories'], [])
                request(b, '/api/account/login', {'username':'user_a', 'password':'safe-password-123'})
                self.assertEqual(len(request(b, '/api/memories')['memories']), 1)
                self.assertEqual(request(b, '/api/account')['localCounts']['memories'], 1)
                with self.assertRaises(HTTPError) as unconfirmed:
                    request(b, '/api/account/migrate', {'confirm':False})
                self.assertEqual(unconfirmed.exception.code, 400)
                request(b, '/api/account/migrate', {'confirm':True})
                self.assertEqual(len(request(a, '/api/memories')['memories']), 2)
                self.assertEqual(len(request(b, '/api/memories')['memories']), 2)
                recovered = request(c, '/api/account/recover',
                                    {'username':'user_a', 'password':'new-safe-password-123',
                                     'recoveryCode':registered['recoveryCode']})
                self.assertEqual(len(recovered['recoveryCode']), 43)
                reissued = request(c, '/api/account/reissue', {'password':'new-safe-password-123'})
                self.assertEqual(len(reissued['recoveryCode']), 43)
                self.assertNotEqual(reissued['recoveryCode'], recovered['recoveryCode'])
                self.assertFalse(request(b, '/api/account')['signedIn'])
                self.assertEqual(len(request(c, '/api/memories')['memories']), 2)
                request(b, '/api/account/login', {'username':'user_a', 'password':'new-safe-password-123'})
                app.sessions.clear()
                self.assertEqual(len(request(b, '/api/memories')['memories']), 2)
                with self.assertRaises(HTTPError) as cross_site:
                    request(b, '/api/memories', {'content':'攻撃'}, origin=False)
                self.assertEqual(cross_site.exception.code, 403)
                request(a, '/api/account/logout', {})
                self.assertFalse(request(a, '/api/account')['signedIn'])
                self.assertEqual(request(a, '/api/memories')['memories'], [])
                self.assertEqual(len(request(b, '/api/memories')['memories']), 2)
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_browser_isolation_persistence_and_memory_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            app = ExhibitionApp(copy.deepcopy(CONFIG))
            app.config['mode'] = 'daily'
            app.daily_store = DailyStore(Path(directory) / 'daily.db')
            app.access_token = ''
            fake = MagicMock()
            fake.status.return_value = ProviderStatus('openai', 'Test', 'test', True)
            fake.generate_stream.side_effect = lambda *args: iter(['こんにちは。'])
            app.providers['openai'] = fake
            class TestHandler(Handler):
                pass
            TestHandler.app = app
            server = ExhibitionHTTPServer(('127.0.0.1', 0), TestHandler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                a = build_opener(HTTPCookieProcessor(CookieJar()))
                b = build_opener(HTTPCookieProcessor(CookieJar()))
                def request(client, path, body=None):
                    data = None if body is None else json.dumps(body).encode()
                    with client.open(Request(base + path, data=data, headers={'Content-Type':'application/json'})) as response:
                        return json.load(response)
                self.assertEqual(request(a, '/api/memories')['memories'], [])
                saved = request(a, '/api/memories', {'content':'ギターの練習中'})['memories'][0]
                self.assertEqual(request(b, '/api/memories')['memories'], [])
                suggestion = request(a, '/api/chat', {'message':'私はギターが好き。'})['memoryProposal']
                self.assertEqual(suggestion['content'], '私はギターが好き')
                self.assertEqual(request(a, '/api/memories')['memories'][0]['content'], 'ギターの練習中')
                self.assertEqual(request(b, '/api/memory-proposals')['proposal'], None)
                request(a, '/api/memory-proposals', {'id':suggestion['id'], 'action':'dismiss'})
                self.assertEqual(request(a, '/api/memory-proposals')['proposal'], None)
                theme = request(a, '/api/themes', {'title':'新しい企画', 'goal':'方向性を決める',
                              'options':'A案・B案', 'open_questions':'予算', 'decisions':'まだなし'})
                theme_id = theme['activeThemeId']
                self.assertEqual(theme['themes'][0]['title'], '新しい企画')
                self.assertEqual(request(b, '/api/themes')['themes'], [])
                with self.assertRaises(HTTPError) as missing_conversation:
                    request(a, '/api/themes/draft', {'id':theme_id})
                self.assertEqual(missing_conversation.exception.code, 400)
                request(a, '/api/chat', {'message':'練習の相談'})
                self.assertIn('ギター', fake.generate_stream.call_args.args[0])
                self.assertIn('方向性を決める', fake.generate_stream.call_args.args[0])
                self.assertEqual(fake.generate_stream.call_args.args[2], 180)
                self.assertEqual(fake.generate_stream.call_args.args[3], 0.55)
                request(a, '/api/chat', {'message':'進路の選択肢を詳しく比較して、長所と弱点を整理して'})
                self.assertGreater(fake.generate_stream.call_args.args[2], 180)
                request(a, '/api/themes', {'action':'select', 'id':None})
                request(a, '/api/chat', {'message':'夕飯はカレーだった'})
                request(a, '/api/themes', {'action':'select', 'id':theme_id})
                fake.generate.return_value = '{"title":"新しい企画","goal":"方向性を決める","options":["A案","B案"],"open_questions":["予算"],"decisions":""}'
                draft = request(a, '/api/themes/draft', {'id':theme_id})['draft']
                self.assertEqual(draft['open_questions'], '予算')
                self.assertEqual(draft['options'], 'A案\nB案')
                self.assertNotIn('夕飯はカレー', fake.generate.call_args.args[1][0]['content'])
                self.assertEqual(request(a, '/api/themes')['themes'][0]['options'], 'A案・B案')
                self.assertEqual(len(next(v for v in app.sessions.values() if v.history).history), 8)
                # Discard process-local sessions to simulate restoring from persistent storage.
                app.sessions.clear()
                request(a, '/api/memories')
                own = next(v for v in app.sessions.values() if v.history)
                self.assertEqual(own.history[-1]['content'], 'こんにちは。')
                self.assertIn('原則90字以内', own._build_chat_prompt('ありがとう')[0])
                self.assertIn('この返事では質問', own._build_chat_prompt('いや、東京だった')[0])
                progress_prompt = own._build_chat_prompt('昨日の相談の続きから。何が決まった？')[0]
                self.assertIn('最終的な選択が決まったか', progress_prompt)
                self.assertIn('実施済みの行動', progress_prompt)
                self.assertEqual(request(a, '/api/themes')['activeThemeId'], theme_id)
                request(a, '/api/themes', {'action':'select', 'id':None})
                self.assertNotIn('方向性を決める', own._build_chat_prompt('相談')[0])
                request(a, '/api/themes', {'action':'select', 'id':theme_id})
                changed = request(a, '/api/memories', {'id':saved['id'], 'content':'ピアノの練習中'})
                self.assertEqual(changed['memories'][0]['content'], 'ピアノの練習中')
                request(a, '/api/memories', {'id':saved['id'], 'action':'delete'})
                self.assertNotIn('ギター', own._build_chat_prompt('好きな楽器は？')[0])
                request(a, '/api/reset', {})
                self.assertEqual(app.daily_store.history(own.owner), [])
                request(a, '/api/chat', {'message':'進路の選択肢を整理して'})
                self.assertGreater(fake.generate_stream.call_args.args[2], 450)
                self.assertIn('日本語250〜350字', fake.generate_stream.call_args.args[0])
                unclear_save = request(a, '/api/chat', {'message':'これ覚えておいて'})
                self.assertIn('どの内容', unclear_save['answer'])
                self.assertEqual(request(a, '/api/memories')['memories'], [])
                remembered = request(a, '/api/chat', {'message':'私は月を見るのが好き。覚えておいて'})
                self.assertIn('覚えたよ', remembered['answer'])
                self.assertEqual(len(request(a, '/api/memories')['memories']), 1)
                self.assertEqual(request(b, '/api/memories')['memories'], [])
                immediate = request(a, '/api/chat', {'message':'それはもう忘れて'})
                self.assertIn('削除したよ', immediate['answer'])
                self.assertEqual(request(a, '/api/memories')['memories'], [])
                request(a, '/api/chat', {'message':'私は月を見るのが好き。覚えておいて'})
                request(a, '/api/chat', {'message':'今日はどう？'})
                ambiguous = request(a, '/api/chat', {'message':'それはもう忘れて'})
                self.assertIn('どの記憶', ambiguous['answer'])
                self.assertEqual(len(request(a, '/api/memories')['memories']), 1)
                forgotten = request(a, '/api/chat', {'message':'月を見るのが好きのことを忘れて'})
                self.assertIn('削除したよ', forgotten['answer'])
                self.assertEqual(request(a, '/api/memories')['memories'], [])
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_chat_approval_clears_pending_memory_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            app = ExhibitionApp(copy.deepcopy(CONFIG))
            app.config['mode'] = 'daily'
            app.daily_store = DailyStore(Path(directory) / 'daily.db')
            app.access_token = ''
            fake = MagicMock()
            fake.status.return_value = ProviderStatus('openai', 'Test', 'test', True)
            fake.generate_stream.side_effect = lambda *args: iter(['いいね。'])
            app.providers['openai'] = fake
            class TestHandler(Handler):
                pass
            TestHandler.app = app
            server = ExhibitionHTTPServer(('127.0.0.1', 0), TestHandler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                client = build_opener(HTTPCookieProcessor(CookieJar()))
                def request(path, body=None):
                    data = None if body is None else json.dumps(body).encode()
                    with client.open(Request(base + path, data=data, headers={'Content-Type':'application/json'})) as response:
                        return json.load(response)
                proposal = request('/api/chat', {'message':'私は星を見るのが好き。'})['memoryProposal']
                self.assertEqual(proposal['content'], '私は星を見るのが好き')
                self.assertTrue(request('/api/memory-proposals')['proposal'])
                approval = request('/api/chat', {'message':'これ覚えておいて'})
                self.assertTrue(approval['memoriesChanged'])
                self.assertEqual(request('/api/memories')['memories'][0]['content'], proposal['content'])
                self.assertIsNone(request('/api/memory-proposals')['proposal'])
                second = request('/api/chat', {'message':'私は音楽を聴くのが好き。'})['memoryProposal']
                self.assertIsNotNone(second)
                yes = request('/api/chat', {'message':'うん。'})
                self.assertIn('覚えたよ', yes['answer'])
                self.assertIsNone(request('/api/memory-proposals')['proposal'])
                third = request('/api/chat', {'message':'私は映画を見るのが好き。'})['memoryProposal']
                self.assertIsNotNone(third)
                no = request('/api/chat', {'message':'今はいい。'})
                self.assertTrue(no['proposalResolved'])
                self.assertEqual(len(request('/api/memories')['memories']), 2)
                self.assertIsNone(request('/api/memory-proposals')['proposal'])
                fourth = request('/api/chat', {'message':'私は大阪の街が好き。'})['memoryProposal']
                self.assertIsNotNone(fourth)
                correction = request('/api/chat', {'message':'いや、東京のほうが好きだった。'})
                self.assertTrue(correction['proposalResolved'])
                self.assertIsNone(request('/api/memory-proposals')['proposal'])
                self.assertEqual(len(request('/api/memories')['memories']), 2)
            finally:
                server.shutdown()
                server.server_close()
                worker.join()
