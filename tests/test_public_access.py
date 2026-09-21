import os
import time
import unittest
from unittest.mock import patch

from exhibition_server import ExhibitionApp


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


if __name__ == "__main__":
    unittest.main()
