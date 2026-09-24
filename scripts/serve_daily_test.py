"""Temporary local browser-test server; never touches the user's daily.db."""
import tempfile
from pathlib import Path

from daily_store import DailyStore
from exhibition_server import ExhibitionApp, ExhibitionHTTPServer, Handler
from persona_chat_prototype import load_config


def main():
    with tempfile.TemporaryDirectory() as directory:
        config = load_config()
        config['mode'] = 'daily'
        app = ExhibitionApp(config)
        app.daily_store = DailyStore(Path(directory) / 'daily.db')
        app.access_token = ''
        class TestHandler(Handler):
            pass
        TestHandler.app = app
        server = ExhibitionHTTPServer(('127.0.0.1', 8766), TestHandler)
        print('TEST_SERVER_READY 8766', flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
