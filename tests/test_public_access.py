import os
import time
import unittest
from unittest.mock import patch

from exhibition_server import ExhibitionApp, Handler


CONFIG = {
    "name": "リク",
    "pronoun": "俺",
    "user_nickname": "お前",
    "mood": "元気",
    "current_interest": "展示",
    "model": "test-model",
    "default_provider": "openai",
    "providers": {"openai": {"label": "OpenAI", "model": "test"}},
    "exhibition": {},
}


class PublicAccessTests(unittest.TestCase):
    def test_access_token_is_loaded_from_environment(self):
        with patch.dict(os.environ, {"EXHIBITION_ACCESS_TOKEN": "invite-secret"}):
            app = ExhibitionApp(CONFIG)
        self.assertEqual(app.access_token, "invite-secret")

    def test_chat_rate_limit(self):
        app = ExhibitionApp(CONFIG)
        self.assertTrue(app.allow_chat_request("visitor", limit=2))
        self.assertTrue(app.allow_chat_request("visitor", limit=2))
        self.assertFalse(app.allow_chat_request("visitor", limit=2))

    def test_private_https_proxy_requires_exact_host_and_forwarded_https(self):
        with patch.dict(os.environ, {"EXHIBITION_HTTPS_PROXY_HOST": "my-pc.example.ts.net",
                                     "EXHIBITION_ACCESS_TOKEN": ""}):
            app = ExhibitionApp(CONFIG)
        class ProxyHandler(Handler):
            pass
        ProxyHandler.app = app
        handler = object.__new__(ProxyHandler)
        handler.client_address = ('127.0.0.1', 1234)
        handler.headers = {'Host':'my-pc.example.ts.net', 'X-Forwarded-Proto':'https'}
        self.assertTrue(handler._account_cookie_secure())
        handler.headers['Host'] = 'other.example.ts.net'
        self.assertFalse(handler._account_cookie_secure())
        handler.headers['Host'] = 'my-pc.example.ts.net'
        handler.headers['X-Forwarded-Proto'] = 'http'
        self.assertFalse(handler._account_cookie_secure())
        handler.headers['X-Forwarded-Proto'] = 'https'
        handler.client_address = ('192.0.2.1', 1234)
        self.assertFalse(handler._account_cookie_secure())


if __name__ == "__main__":
    unittest.main()
