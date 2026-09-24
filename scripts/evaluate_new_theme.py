"""Probe whether a new theme draft mixes older unrelated conversation."""
import json
import tempfile
from pathlib import Path

from daily_store import DailyStore
from exhibition_server import ExhibitionApp
from persona_chat_prototype import load_config


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = ExhibitionApp(load_config())
        app.daily_store = DailyStore(Path(directory) / 'daily.db')
        app.owner = app.daily_store.create_identity()
        turns = [
            ('私はギターを練習している。コードがまだ難しい。', '毎日少しずつやろう。'),
            ('週末は映画を見たい。アクションとコメディで迷う。', '気分で決めよう。'),
            ('進路を相談したい。大学で情報学を学ぶか、就職して現場で学ぶか迷っている。', '比べてみよう。'),
            ('目標は半年以内に方向性を決めること。学費と就職後の学習時間がまだ不明。', '確認項目を整理しよう。'),
        ]
        for user, answer in turns:
            app.daily_store.append_turn(app.owner, user, answer)
        app.history = app.daily_store.history(app.owner)
        draft = app.draft_theme()
        print(json.dumps({'scenario':'latest_substantive', 'draft':draft}, ensure_ascii=False), flush=True)
        app.daily_store.append_turn(app.owner, 'ありがとう。', 'どういたしまして。')
        app.history = app.daily_store.history(app.owner)
        draft = app.draft_theme()
        print(json.dumps({'scenario':'after_thanks', 'draft':draft}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
