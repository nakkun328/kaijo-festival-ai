"""Exercise the running local server using a separate test browser identity."""
import json
import httpx


def main():
    with httpx.Client(base_url='http://127.0.0.1:8765', timeout=180) as client:
        def post(path, **body):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()
        bootstrap = client.get('/api/bootstrap').json()
        print(json.dumps({'warmup':bootstrap['warmup']['ready'], 'title':bootstrap['title']}, ensure_ascii=True), flush=True)
        memory = post('/api/memories', content='検証用：今はギターの練習に取り組んでいる。')['memories'][0]
        try:
            for question in ['今取り組んでいる楽器、覚えてる？', '明日の東京の天気を教えて']:
                answer = post('/api/chat', message=question)
                print(json.dumps({'question':question,'answer':answer['answer'],'sources':answer.get('sources',[])},ensure_ascii=True),flush=True)
            voice = client.post('/api/voice', json={'text':'こんにちは、今日は少し話そう。'})
            voice.raise_for_status()
            recognized = client.post('/api/analyze-turn', content=voice.content, headers={'Content-Type':'audio/wav'})
            recognized.raise_for_status()
            print(json.dumps({'audioBytes':len(voice.content),'recognition':recognized.json()},ensure_ascii=True),flush=True)
            restored = client.get('/api/bootstrap').json()['history']
            assert len(restored) == 4 and restored[-1].get('sources')
            print('PASS: persisted history and sources', flush=True)
        finally:
            post('/api/memories', id=memory['id'], action='delete')
            post('/api/reset')


if __name__ == '__main__':
    main()
