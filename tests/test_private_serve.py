import copy
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from daily_store import DailyStore
from exhibition_server import ExhibitionApp, ExhibitionHTTPServer, Handler
from private_serve import hostname_from_status, login_from_status
from test_exhibition_server import CONFIG


class PrivateServeTests(unittest.TestCase):
    def test_accepts_connected_tailscale_dns_name(self):
        self.assertEqual(hostname_from_status({
            'BackendState':'Running', 'Self':{'DNSName':'MY-PC.tailabc.ts.net.'}}),
            'my-pc.tailabc.ts.net')

    def test_rejects_disconnected_or_unexpected_host(self):
        with self.assertRaises(RuntimeError):
            hostname_from_status({'BackendState':'Stopped', 'Self':{'DNSName':'pc.tailabc.ts.net.'}})
        with self.assertRaises(RuntimeError):
            hostname_from_status({'BackendState':'Running', 'Self':{'DNSName':'evil.example.com.'}})

    def test_owner_login_must_be_available_from_tailscale_status(self):
        self.assertEqual(login_from_status({'Self':{'UserID':42},
                                            'User':{'42':{'LoginName':'Owner@Example.com'}}}),
                         'owner@example.com')
        with self.assertRaises(RuntimeError):
            login_from_status({'Self':{'UserID':42}, 'User':{}})

    def test_forwarded_https_allows_secure_account_session(self):
        with tempfile.TemporaryDirectory() as directory:
            app = ExhibitionApp(copy.deepcopy(CONFIG))
            app.config['mode'] = 'daily'
            app.daily_store = DailyStore(Path(directory) / 'daily.db')
            app.access_token = ''
            app.trusted_https_host = 'my-pc.tailabc.ts.net'
            app.tailscale_login = 'owner@example.com'
            class TestHandler(Handler):
                pass
            TestHandler.app = app
            server = ExhibitionHTTPServer(('127.0.0.1', 0), TestHandler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                def request(method, path, body=None, cookie='', login='owner@example.com'):
                    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    headers = {'Host':'my-pc.tailabc.ts.net', 'X-Forwarded-Proto':'https',
                               'Origin':'https://my-pc.tailabc.ts.net'}
                    if login is not None:
                        headers['Tailscale-User-Login'] = login
                    if cookie:
                        headers['Cookie'] = cookie
                    data = json.dumps(body).encode() if body is not None else None
                    if data is not None:
                        headers['Content-Type'] = 'application/json'
                    conn.request(method, path, body=data, headers=headers)
                    response = conn.getresponse()
                    raw = response.read()
                    try:
                        payload = json.loads(raw)
                    except ValueError:
                        payload = raw.decode('utf-8', errors='replace')
                    cookies = response.getheaders()
                    status = response.status
                    conn.close()
                    return status, payload, [value for key, value in cookies if key.lower() == 'set-cookie']

                status, _, cookies = request('GET', '/api/account', login=None)
                self.assertEqual(status, 404)
                self.assertEqual(cookies, [])
                status, _, _ = request('GET', '/api/account', login='other@example.com')
                self.assertEqual(status, 404)
                status, _, _ = request('GET', '/admin.html', login='other@example.com')
                self.assertEqual(status, 404)
                status, _, _ = request('POST', '/api/reset', login='other@example.com')
                self.assertEqual(status, 404)
                status, _, cookies = request('GET', '/api/account')
                self.assertEqual(status, 200)
                identity = next(value.split(';', 1)[0] for value in cookies if value.startswith('daily_identity='))
                self.assertIn('Secure', next(value for value in cookies if value.startswith('daily_identity=')))
                status, result, cookies = request('POST', '/api/account/register',
                                                  {'username':'private_user', 'password':'long-password-123'}, identity)
                self.assertEqual(status, 200)
                self.assertTrue(result['ok'])
                session = next(value.split(';', 1)[0] for value in cookies
                               if value.startswith('__Host-daily_session='))
                self.assertIn('Secure', next(value for value in cookies
                                             if value.startswith('__Host-daily_session=')))
                status, account, _ = request('GET', '/api/account', cookie=session)
                self.assertEqual(status, 200)
                self.assertTrue(account['signedIn'])
            finally:
                server.shutdown()
                server.server_close()
                worker.join()


if __name__ == '__main__':
    unittest.main()
