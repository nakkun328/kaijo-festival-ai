"""Evaluate a multi-day synthetic theme without reading user data."""
import json
import tempfile
from pathlib import Path

from daily_store import DailyStore
from exhibition_server import ExhibitionApp
from persona_chat_prototype import load_config


def main():
    with tempfile.TemporaryDirectory() as directory:
        store_path = Path(directory) / 'daily.db'
        app = ExhibitionApp(load_config())
        app.daily_store = DailyStore(store_path)
        app.owner = app.daily_store.create_identity()
        theme_id = app.daily_store.save_theme(app.owner, {
            'title':'進路の相談', 'goal':'半年以内に進路の方向性を決める',
            'options':'大学で情報学を学ぶ\n就職して現場で学ぶ',
            'open_questions':'学費と奨学金\n就職後に学ぶ時間を取れるか',
            'decisions':'今週、先輩に話を聞く'})
        turns = [
            ('大学と就職で迷っている。半年以内に方向性を決めたい。', 'それぞれの学び方を比べよう。'),
            ('大学なら情報学を学びたい。就職なら現場で経験を積めそう。', '費用と仕事の条件も見たいね。'),
            ('学費と奨学金がまだ分からない。就職後に学ぶ時間を取れるかも未確認。', '確認項目として残そう。'),
            ('今週、先輩に話を聞くことは決めた。大学に行くかはまだ決めていない。', '決定と未決定を分けて記録しよう。'),
        ]
        for user, answer in turns:
            app.daily_store.append_turn(app.owner, user, answer)
        app.daily_store.select_theme(app.owner, None)
        app.daily_store.append_turn(app.owner, '夕飯はカレーだった。', 'おいしそう。')
        app.daily_store.select_theme(app.owner, theme_id)
        app.daily_store.append_turn(app.owner, '昨日、先輩に話を聞いた。大学の授業は面白そうだけど、費用はまだ調べていない。',
                                    '授業への関心は増えたけれど、費用は未解決だね。')
        owner = app.owner
        app = ExhibitionApp(load_config())
        app.daily_store = DailyStore(store_path)
        app.owner = owner
        app.history = app.daily_store.history(owner)
        assert app.daily_store.themes(owner)['activeThemeId'] == theme_id
        continuation = app.chat_reply('昨日の進路相談の続きから考えたい。何が決まっていて、次に何を確かめるといい？')
        print('CONTINUATION:', continuation['answer'], flush=True)
        original = app.provider.generate

        def capture(*args, **kwargs):
            payload = json.loads(args[1][0]['content'])
            assert not any('夕飯' in item['content'] for item in payload['conversation'])
            raw = original(*args, **kwargs)
            print('RAW:', raw, flush=True)
            return raw
        app.provider.generate = capture
        try:
            print('PARSED:', json.dumps(app.draft_theme(theme_id), ensure_ascii=False), flush=True)
        except Exception as exc:
            print('ERROR:', type(exc).__name__, str(exc), flush=True)


if __name__ == '__main__':
    main()
