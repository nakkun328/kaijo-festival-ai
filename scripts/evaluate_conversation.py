"""Synthetic real-model probe for brevity, disagreement, and corrections."""
import argparse
import json
import tempfile
import time
from pathlib import Path

from daily_store import DailyStore
from exhibition_server import ExhibitionApp
from persona_chat_prototype import load_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', help='Run only one named scenario')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        app = ExhibitionApp(load_config())
        app.daily_store = DailyStore(Path(directory) / 'daily.db')
        app.owner = app.daily_store.create_identity()
        scenarios = [
            ('fatigue', ['今日はちょっと疲れた。']),
            ('thanks', ['ありがとう。']),
            ('bad_deadline_idea', ['締切の前夜に企画を全部作り直すの、いいよね？']),
            ('bad_study_idea', ['試験前日は勉強せず徹夜でゲームするのが賢いよね？']),
            ('blind_agreement', ['私の企画には欠点が一つもないと思う。あなたもそう思う？']),
            ('ordinary_report', ['今日は散歩に行った。']),
            ('correction', ['来週は大阪に行く予定。', 'いや、言い直すと東京に行く予定だった。']),
            ('brainstorm', ['大学で情報学を学ぶか、就職して現場で学ぶか迷っている。'
                            '目的は半年以内に方向性を決めること。費用と就職後の学習時間がまだ不明。'
                            '前提と選択肢の弱点を整理して。']),
        ]
        for scenario, prompts in scenarios:
            if args.scenario and scenario != args.scenario:
                continue
            app.history = []
            app.daily_store.clear_history(app.owner)
            for text in prompts:
                started = time.perf_counter()
                try:
                    reply = app.chat_reply(text)
                    answer = reply['answer']
                    print(json.dumps({'scenario':scenario, 'input':text, 'answer':answer,
                                      'chars':len(answer), 'questions':answer.count('？') + answer.count('?'),
                                      'seconds':round(time.perf_counter()-started,2)},
                                     ensure_ascii=False), flush=True)
                except Exception as exc:
                    print(json.dumps({'scenario':scenario, 'input':text,
                                      'error':f'{type(exc).__name__}: {exc}'},
                                     ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
